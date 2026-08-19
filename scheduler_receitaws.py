import argparse
import logging
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler

from database.db_conection import DatabaseConnection
from database.receitaws_cache import ReceitaWsCache
from services.receitaws_client import ReceitaWsClient, ReceitaWsErro


FUSO_HORARIO = ZoneInfo("America/Sao_Paulo")


def obter_inteiro_env(nome: str, padrao: int, minimo: int = 0) -> int:
    try:
        valor = int(os.getenv(nome, str(padrao)))
    except (TypeError, ValueError):
        logging.warning("%s inválido; usando %s.", nome, padrao)
        return padrao
    return max(minimo, valor)


def obter_esperas_429() -> tuple[int, ...]:
    """
    Retorna as pausas progressivas usadas após respostas HTTP 429.

    Padrão:
    1º 429: 90 segundos
    2º 429: 180 segundos
    3º 429: 300 segundos
    4º 429: 600 segundos
    5º 429: encerra o lote
    """
    padrao = (90, 180, 300, 600)
    valor = os.getenv("RECEITAWS_ESPERAS_429_SEGUNDOS", "")

    if not valor.strip():
        return padrao

    try:
        esperas = tuple(
            max(30, int(item.strip()))
            for item in valor.split(",")
            if item.strip()
        )

        if not esperas:
            raise ValueError

        return esperas
    except (TypeError, ValueError):
        logging.warning(
            "RECEITAWS_ESPERAS_429_SEGUNDOS inválido; usando %s.",
            ",".join(str(item) for item in padrao),
        )
        return padrao


def listar_matrizes_ativas() -> list:
    db = DatabaseConnection()
    if not db.connect():
        raise RuntimeError("Não foi possível conectar ao banco da Domínio.")
    try:
        return db.get_matrizes_ativas_para_receitaws()
    finally:
        db.close()


def sincronizar_receitaws(limite=None) -> dict:
    """
    Atualiza o cache sem manter a conexão da Domínio durante as chamadas HTTP.

    Quando a ReceitaWS retorna HTTP 429, aguarda e repete o mesmo CNPJ.
    Os CNPJs concluídos anteriormente permanecem gravados no cache.
    """
    ttl_dias = obter_inteiro_env(
        "RECEITAWS_TTL_DIAS",
        30,
        minimo=1,
    )
    intervalo = obter_inteiro_env(
        "RECEITAWS_INTERVALO_SEGUNDOS",
        23,
        minimo=20,
    )
    limite_padrao = obter_inteiro_env(
        "RECEITAWS_MAX_POR_EXECUCAO",
        40,
        minimo=1,
    )
    esperas_429 = obter_esperas_429()

    # -1 é usado internamente para a carga inicial completa.
    limite_efetivo = (
        None
        if limite == -1
        else limite_padrao if limite is None else limite
    )

    empresas = listar_matrizes_ativas()
    cache = ReceitaWsCache()

    pendentes = cache.selecionar_pendentes(
        empresas,
        ttl_dias=ttl_dias,
        limite=limite_efetivo,
    )

    cliente = ReceitaWsClient()

    resumo = {
        "matrizes": len(empresas),
        "pendentes": len(pendentes),
        "sucessos": 0,
        "erros": 0,
        "pausas_429": 0,
        "interrompido_por_limite": False,
    }

    logging.info(
        "ReceitaWS: %s matrizes ativas, %s consulta(s) selecionada(s).",
        resumo["matrizes"],
        resumo["pendentes"],
    )

    instante_ultima_chamada = None
    interromper_lote = False

    for posicao, empresa in enumerate(pendentes, start=1):
        cnpj = empresa["cnpj"]
        respostas_429_consecutivas = 0

        while True:
            if instante_ultima_chamada is not None:
                tempo_decorrido = (
                    time.monotonic() - instante_ultima_chamada
                )
                espera_intervalo = intervalo - tempo_decorrido

                if espera_intervalo > 0:
                    time.sleep(espera_intervalo)

            logging.info(
                "ReceitaWS [%s/%s]: consultando %s — %s.",
                posicao,
                len(pendentes),
                cnpj,
                empresa.get("razao_social")
                or "empresa sem razão social",
            )

            instante_ultima_chamada = time.monotonic()

            try:
                payload = cliente.consultar(cnpj)
                cache.salvar_sucesso(cnpj, payload)

                resumo["sucessos"] += 1
                respostas_429_consecutivas = 0
                break

            except ReceitaWsErro as exc:
                if exc.http_status == 429:
                    respostas_429_consecutivas += 1

                    # Quatro pausas configuradas significam que a quinta
                    # resposta 429 consecutiva encerra o lote.
                    if respostas_429_consecutivas > len(esperas_429):
                        resumo["interrompido_por_limite"] = True
                        interromper_lote = True

                        logging.error(
                            "ReceitaWS: limite permaneceu ativo após "
                            "%s respostas 429 consecutivas. "
                            "O lote será encerrado e poderá ser retomado.",
                            respostas_429_consecutivas,
                        )
                        break

                    espera_configurada = esperas_429[
                        respostas_429_consecutivas - 1
                    ]
                    espera_informada_api = int(exc.retry_after or 0)

                    # Nunca espera menos do que nossa pausa configurada,
                    # mas respeita um Retry-After maior enviado pela API.
                    espera_efetiva = max(
                        espera_configurada,
                        espera_informada_api,
                    )

                    resumo["pausas_429"] += 1

                    logging.warning(
                        "ReceitaWS: HTTP 429 ao consultar %s. "
                        "Aguardando %s segundo(s) antes de repetir "
                        "o mesmo CNPJ. Pausa %s de %s.",
                        cnpj,
                        espera_efetiva,
                        respostas_429_consecutivas,
                        len(esperas_429),
                    )

                    time.sleep(espera_efetiva)
                    continue

                cache.salvar_erro(
                    cnpj,
                    str(exc),
                    exc.http_status,
                )
                resumo["erros"] += 1

                logging.warning(
                    "ReceitaWS: %s (%s).",
                    exc,
                    cnpj,
                )
                break

            except Exception as exc:
                cache.salvar_erro(
                    cnpj,
                    str(exc),
                )
                resumo["erros"] += 1

                logging.exception(
                    "Erro inesperado ao consultar %s: %s",
                    cnpj,
                    exc,
                )
                break

        if interromper_lote:
            break

    logging.info(
        "ReceitaWS: rotina concluída — %s.",
        resumo,
    )

    return resumo


def sincronizar_cnpj_especifico(cnpj) -> dict:
    """Consulta um único CNPJ e grava o resultado no mesmo cache do painel."""
    cliente = ReceitaWsClient()
    cache = ReceitaWsCache()
    cnpj_limpo = cliente.normalizar_cnpj(cnpj)

    logging.info("ReceitaWS: consultando CNPJ específico %s.", cnpj_limpo)
    try:
        payload = cliente.consultar(cnpj_limpo)
        cache.salvar_sucesso(cnpj_limpo, payload)
        logging.info("ReceitaWS: CNPJ %s atualizado com sucesso no cache.", cnpj_limpo)
        return {"cnpj": cnpj_limpo, "sucesso": True}
    except ReceitaWsErro as exc:
        cache.salvar_erro(cnpj_limpo, str(exc), exc.http_status)
        logging.error("ReceitaWS: %s (%s).", exc, cnpj_limpo)
        return {"cnpj": cnpj_limpo, "sucesso": False, "erro": str(exc)}


def parse_horario(valor: str) -> tuple[int, int]:
    try:
        hora_texto, minuto_texto = valor.strip().split(":", 1)
        hora, minuto = int(hora_texto), int(minuto_texto)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("RECEITAWS_HORA deve estar no formato HH:MM.") from exc
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        raise ValueError("RECEITAWS_HORA deve conter um horário válido.")
    return hora, minuto


def iniciar_agendador():
    hora, minuto = parse_horario(os.getenv("RECEITAWS_HORA", "07:00"))
    scheduler = BlockingScheduler(timezone=FUSO_HORARIO)
    scheduler.add_job(
        sincronizar_receitaws,
        trigger="cron",
        hour=hora,
        minute=minuto,
        id="sincronizacao_receitaws",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    proxima = datetime.now(FUSO_HORARIO).strftime("%d/%m/%Y %H:%M:%S")
    logging.info(
        "Agendador ReceitaWS iniciado às %s; execução diária configurada para %02d:%02d.",
        proxima,
        hora,
        minuto,
    )
    scheduler.start()


def main():
    parser = argparse.ArgumentParser(description="Atualização do cache ReceitaWS do painel e-BEF.")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument("--executar-agora", action="store_true", help="Executa um lote e encerra.")
    grupo.add_argument(
        "--carga-inicial",
        action="store_true",
        help="Consulta todas as matrizes ausentes ou vencidas, respeitando o intervalo da API.",
    )
    grupo.add_argument(
        "--cnpj",
        help="Consulta imediatamente um único CNPJ e grava o resultado no cache.",
    )
    parser.add_argument("--limite", type=int, help="Limite de CNPJs para a execução manual.")
    args = parser.parse_args()

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.carga_inicial:
        sincronizar_receitaws(limite=args.limite if args.limite is not None else -1)
        return
    if args.executar_agora:
        limite = args.limite
        sincronizar_receitaws(limite=limite)
        return
    if args.cnpj:
        sincronizar_cnpj_especifico(args.cnpj)
        return
    iniciar_agendador()


if __name__ == "__main__":
    main()
