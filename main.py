import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template, request

from database.comunicacao_envios import HistoricoEnviosEbef
from database.db_conection import DatabaseConnection
from database.receitaws_cache import ReceitaWsCache
from services.email_service import EmailEbefService


app = Flask(__name__)
FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


def obter_ano_apresentacao_padrao() -> int:
    try:
        return DatabaseConnection.validar_ano_apresentacao(
            DatabaseConnection.obter_ano_apresentacao_padrao()
        )
    except ValueError as exc:
        ano_atual = datetime.now(FUSO_BRASIL).year
        logging.warning(
            "Ano padrão do e-BEF inválido no .env (%s). Usando %s.",
            exc,
            ano_atual,
        )
        return max(DatabaseConnection.ANO_INICIO_EBEF, ano_atual)


def obter_anos_disponiveis() -> list[int]:
    ano_atual = datetime.now(FUSO_BRASIL).year
    return list(range(DatabaseConnection.ANO_INICIO_EBEF, ano_atual + 1))


def montar_empresas_comunicacao(db: DatabaseConnection) -> list:
    relatorio = db.get_relatorio_ebef()
    contatos = db.get_contatos_comunicacao_ebef()
    contatos_por_codigo = {str(item["codigo"]): item for item in contatos}
    relatorio_por_codigo = {str(item["codigo"]): item for item in relatorio}

    historico = HistoricoEnviosEbef()
    codigos_manuais = set(historico.listar_inclusoes_manuais(db.ano_apresentacao))
    empresas_por_codigo = {}

    for empresa in relatorio:
        if empresa.get("status_codigo") != "OBRIGADA":
            continue

        codigo = str(empresa.get("codigo"))
        contato = contatos_por_codigo.get(codigo, {})
        empresas_por_codigo[codigo] = {
            "codigo": empresa.get("codigo"),
            "razao_social": empresa.get("razao_social"),
            "cnpj": empresa.get("cnpj"),
            "email": contato.get("email", ""),
            "email_preenchido": contato.get("email_preenchido", False),
            "email_valido": contato.get("email_valido", False),
            "origem": "AUTOMATICA",
            "inclusao_manual": False,
            "status_auditoria": empresa.get("status_codigo"),
            "motivo_auditoria": empresa.get("motivo_curto"),
        }

    for codigo in codigos_manuais:
        if codigo in empresas_por_codigo:
            continue

        contato = contatos_por_codigo.get(codigo)
        if not contato:
            logging.warning(
                "Inclusão manual e-BEF ignorada: empresa %s não é uma matriz ativa disponível na Domínio.",
                codigo,
            )
            continue

        auditoria = relatorio_por_codigo.get(codigo, {})
        empresas_por_codigo[codigo] = {
            "codigo": contato.get("codigo"),
            "razao_social": contato.get("razao_social"),
            "cnpj": contato.get("cnpj"),
            "email": contato.get("email", ""),
            "email_preenchido": contato.get("email_preenchido", False),
            "email_valido": contato.get("email_valido", False),
            "origem": "MANUAL",
            "inclusao_manual": True,
            "status_auditoria": auditoria.get("status_codigo"),
            "motivo_auditoria": auditoria.get("motivo_curto"),
        }

    empresas = list(empresas_por_codigo.values())
    empresas.sort(key=lambda item: str(item.get("razao_social") or "").lower())

    resumo_envios = historico.obter_resumo_empresas(
        db.ano_apresentacao,
        [empresa["codigo"] for empresa in empresas],
    )

    for empresa in empresas:
        resumo = resumo_envios.get(str(empresa["codigo"]), {})
        empresa.update({
            "ja_enviado": bool(resumo.get("ja_enviado", False)),
            "ultimo_envio_em": resumo.get("ultimo_envio_em"),
            "ultimo_email_enviado": resumo.get("ultimo_email_enviado"),
            "ultima_tentativa_status": resumo.get("ultima_tentativa_status"),
            "ultima_tentativa_em": resumo.get("ultima_tentativa_em"),
            "ultimo_erro": resumo.get("ultimo_erro"),
        })

    return empresas


@app.route("/")
def index():
    return render_template(
        "index.html",
        anos_disponiveis=obter_anos_disponiveis(),
        ano_apresentacao_padrao=obter_ano_apresentacao_padrao(),
    )


@app.route("/comunicacao")
def comunicacao():
    return render_template(
        "comunicacao.html",
        anos_disponiveis=obter_anos_disponiveis(),
        ano_apresentacao_padrao=obter_ano_apresentacao_padrao(),
    )


@app.route("/api/ebef")
def api_ebef():
    ano_solicitado = request.args.get(
        "ano_apresentacao",
        request.args.get("ano", obter_ano_apresentacao_padrao()),
    )

    try:
        ano_apresentacao = DatabaseConnection.validar_ano_apresentacao(ano_solicitado)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    db = DatabaseConnection(ano_apresentacao=ano_apresentacao)
    if not db.connect():
        return jsonify({"error": "Falha ao conectar no banco de dados da Domínio."}), 500

    try:
        dados = db.get_relatorio_ebef()

        try:
            dados = ReceitaWsCache().enriquecer_empresas(dados)
        except Exception as exc:
            logging.exception("Não foi possível ler o cache da ReceitaWS: %s", exc)
            for empresa in dados:
                empresa["receitaws"] = {
                    "disponivel": False,
                    "status_consulta": "INDISPONIVEL",
                    "origem_qsa_status": "INDISPONIVEL",
                    "possui_socio_internacional": False,
                    "qsa": [],
                    "paises": [],
                }

        return jsonify(
            {
                "dados": dados,
                "meta": {
                    "total": len(dados),
                    "ano_apresentacao": db.ano_apresentacao,
                    "ano_referencia": db.ano_referencia,
                    "gerado_em": datetime.now(FUSO_BRASIL).isoformat(),
                    "classificacao_preliminar": True,
                    "receitaws_complementar": True,
                },
            }
        )
    except Exception as exc:
        logging.exception("Erro inesperado ao montar relatório e-BEF: %s", exc)
        return jsonify({"error": "Erro ao montar o relatório de auditoria."}), 500
    finally:
        db.close()


@app.route("/api/comunicacao-ebef/preview", methods=["POST"])
def api_preview_comunicacao_ebef():
    payload = request.get_json(silent=True) or {}
    razao_social = str(payload.get("razao_social") or "").strip()
    cnpj = str(payload.get("cnpj") or "").strip()

    if not razao_social or not cnpj:
        return jsonify({
            "error": "Razão social e CNPJ são obrigatórios para montar a prévia."
        }), 400

    try:
        servico_email = EmailEbefService()
        preview = servico_email.montar_preview(
            destinatario=str(payload.get("email") or ""),
            razao_social=razao_social,
            cnpj=cnpj,
        )
        return jsonify(preview)

    except Exception as exc:
        logging.exception(
            "Erro ao montar prévia da comunicação e-BEF: %s",
            exc,
        )
        return jsonify({
            "error": "Não foi possível montar a prévia do e-mail."
        }), 500


@app.route("/api/comunicacao-ebef")
def api_comunicacao_ebef():
    ano_solicitado = request.args.get(
        "ano_apresentacao",
        request.args.get("ano", obter_ano_apresentacao_padrao()),
    )

    try:
        ano_apresentacao = DatabaseConnection.validar_ano_apresentacao(ano_solicitado)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    db = DatabaseConnection(ano_apresentacao=ano_apresentacao)
    if not db.connect():
        return jsonify({"error": "Falha ao conectar no banco de dados da Domínio."}), 500

    try:
        empresas = montar_empresas_comunicacao(db)
        com_email_valido = sum(1 for empresa in empresas if empresa["email_valido"])
        sem_email = sum(1 for empresa in empresas if not empresa["email_preenchido"])
        email_invalido = sum(
            1 for empresa in empresas
            if empresa["email_preenchido"] and not empresa["email_valido"]
        )
        total_automaticas = sum(1 for empresa in empresas if empresa.get("origem") == "AUTOMATICA")
        total_manuais = sum(1 for empresa in empresas if empresa.get("origem") == "MANUAL")
        ja_enviadas = sum(1 for empresa in empresas if empresa["ja_enviado"])
        destino_teste = os.getenv("EBEF_EMAIL_DESTINO_TESTE", "").strip()

        return jsonify(
            {
                "dados": empresas,
                "meta": {
                    "total_comunicacao": len(empresas),
                    "total_obrigadas": total_automaticas,
                    "total_manuais": total_manuais,
                    "com_email_valido": com_email_valido,
                    "sem_email": sem_email,
                    "email_invalido": email_invalido,
                    "ja_enviadas": ja_enviadas,
                    "nao_enviadas": max(0, len(empresas) - ja_enviadas),
                    "ano_apresentacao": db.ano_apresentacao,
                    "gerado_em": datetime.now(FUSO_BRASIL).isoformat(),
                    "assunto_email": os.getenv(
                        "EBEF_EMAIL_ASSUNTO",
                        "Comunicado - e-BEF - Formulário Digital de Beneficiários Finais",
                    ),
                    "comunicado_anexo": EmailEbefService.NOME_ANEXO,
                    "modo_teste": bool(destino_teste),
                    "destino_teste": destino_teste,
                },
            }
        )
    except Exception as exc:
        logging.exception("Erro ao montar comunicação e-BEF: %s", exc)
        return jsonify({"error": "Erro ao montar a lista de comunicação e-BEF."}), 500
    finally:
        db.close()


@app.route("/api/comunicacao-ebef/candidatas")
def api_candidatas_comunicacao_ebef():
    ano_solicitado = request.args.get("ano_apresentacao", obter_ano_apresentacao_padrao())
    termo = str(request.args.get("q") or "").strip()

    try:
        ano_apresentacao = DatabaseConnection.validar_ano_apresentacao(ano_solicitado)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not termo:
        return jsonify({"dados": []})

    db = DatabaseConnection(ano_apresentacao=ano_apresentacao)
    if not db.connect():
        return jsonify({"error": "Falha ao conectar no banco de dados da Domínio."}), 500

    try:
        contatos = db.get_contatos_comunicacao_ebef()
        manuais = set(HistoricoEnviosEbef().listar_inclusoes_manuais(ano_apresentacao))
        termo_lower = termo.lower()
        termo_normalizado = "".join(caractere for caractere in termo_lower if caractere.isalnum())
        resultados = []

        for contato in contatos:
            codigo = str(contato.get("codigo"))
            texto = " ".join([
                codigo,
                str(contato.get("razao_social") or ""),
                str(contato.get("cnpj") or ""),
                str(contato.get("email") or ""),
            ]).lower()
            texto_normalizado = "".join(caractere for caractere in texto if caractere.isalnum())

            if termo_lower not in texto and termo_normalizado not in texto_normalizado:
                continue

            resultados.append({
                "codigo": contato.get("codigo"),
                "razao_social": contato.get("razao_social"),
                "cnpj": contato.get("cnpj"),
                "email": contato.get("email", ""),
                "email_preenchido": contato.get("email_preenchido", False),
                "email_valido": contato.get("email_valido", False),
                "inclusao_manual_ativa": codigo in manuais,
            })

        resultados.sort(key=lambda item: str(item.get("razao_social") or "").lower())
        return jsonify({"dados": resultados[:50]})
    except Exception as exc:
        logging.exception("Erro ao buscar empresas para inclusão manual na comunicação e-BEF: %s", exc)
        return jsonify({"error": "Não foi possível buscar empresas para inclusão."}), 500
    finally:
        db.close()


@app.route("/api/comunicacao-ebef/inclusao-manual", methods=["POST"])
def api_incluir_empresa_comunicacao_ebef():
    payload = request.get_json(silent=True) or {}
    ano_solicitado = payload.get("ano_apresentacao", obter_ano_apresentacao_padrao())
    codigo = str(payload.get("codigo_empresa") or "").strip()

    try:
        ano_apresentacao = DatabaseConnection.validar_ano_apresentacao(ano_solicitado)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not codigo:
        return jsonify({"error": "Informe a empresa que será incluída."}), 400

    historico = HistoricoEnviosEbef()
    if codigo in set(historico.listar_inclusoes_manuais(ano_apresentacao)):
        return jsonify({"error": "A empresa já possui inclusão manual ativa neste ano."}), 409

    db = DatabaseConnection(ano_apresentacao=ano_apresentacao)
    if not db.connect():
        return jsonify({"error": "Falha ao conectar no banco de dados da Domínio."}), 500

    try:
        contatos = {str(item["codigo"]): item for item in db.get_contatos_comunicacao_ebef()}
        contato = contatos.get(codigo)
        if not contato:
            return jsonify({"error": "A empresa não foi localizada entre as matrizes ativas da Domínio."}), 404

        historico.incluir_empresa_manual(ano_apresentacao, codigo)
        resumo = historico.obter_resumo_empresas(ano_apresentacao, [contato.get("codigo")]).get(codigo, {})

        return jsonify({
            "ok": True,
            "empresa": {
                "codigo": contato.get("codigo"),
                "razao_social": contato.get("razao_social"),
                "cnpj": contato.get("cnpj"),
                "email": contato.get("email", ""),
                "email_preenchido": contato.get("email_preenchido", False),
                "email_valido": contato.get("email_valido", False),
                "origem": "MANUAL",
                "inclusao_manual": True,
                "status_auditoria": None,
                "motivo_auditoria": None,
                "ja_enviado": bool(resumo.get("ja_enviado", False)),
                "ultimo_envio_em": resumo.get("ultimo_envio_em"),
                "ultimo_email_enviado": resumo.get("ultimo_email_enviado"),
                "ultima_tentativa_status": resumo.get("ultima_tentativa_status"),
                "ultima_tentativa_em": resumo.get("ultima_tentativa_em"),
                "ultimo_erro": resumo.get("ultimo_erro"),
            },
        })
    except Exception as exc:
        logging.exception("Erro ao incluir empresa manualmente na comunicação e-BEF: %s", exc)
        return jsonify({"error": "Não foi possível incluir a empresa na comunicação."}), 500
    finally:
        db.close()


@app.route("/api/comunicacao-ebef/inclusao-manual", methods=["DELETE"])
def api_remover_empresa_comunicacao_ebef():
    payload = request.get_json(silent=True) or {}
    ano_solicitado = payload.get("ano_apresentacao", obter_ano_apresentacao_padrao())
    codigo = str(payload.get("codigo_empresa") or "").strip()

    try:
        ano_apresentacao = DatabaseConnection.validar_ano_apresentacao(ano_solicitado)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not codigo:
        return jsonify({"error": "Informe a empresa que será removida."}), 400

    removida = HistoricoEnviosEbef().remover_empresa_manual(ano_apresentacao, codigo)
    if not removida:
        return jsonify({"error": "A empresa não possui inclusão manual ativa neste ano."}), 404

    return jsonify({"ok": True})


@app.route("/api/comunicacao-ebef/enviar", methods=["POST"])
def api_enviar_comunicacao_ebef():
    payload = request.get_json(silent=True) or {}
    ano_solicitado = payload.get("ano_apresentacao", obter_ano_apresentacao_padrao())
    codigos_recebidos = payload.get("codigos_empresa", [])
    forcar_reenvio = bool(payload.get("forcar_reenvio", False))

    try:
        ano_apresentacao = DatabaseConnection.validar_ano_apresentacao(ano_solicitado)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if not isinstance(codigos_recebidos, list):
        return jsonify({"error": "codigos_empresa deve ser uma lista."}), 400

    codigos = []
    vistos = set()
    for codigo in codigos_recebidos:
        chave = str(codigo).strip()
        if chave and chave not in vistos:
            vistos.add(chave)
            codigos.append(chave)

    if not codigos:
        return jsonify({"error": "Selecione pelo menos uma empresa para envio."}), 400
    if len(codigos) > 300:
        return jsonify({"error": "O lote está limitado a 300 empresas por envio."}), 400

    db = DatabaseConnection(ano_apresentacao=ano_apresentacao)
    if not db.connect():
        return jsonify({"error": "Falha ao conectar no banco de dados da Domínio."}), 500

    try:
        empresas = montar_empresas_comunicacao(db)
        empresas_por_codigo = {str(empresa["codigo"]): empresa for empresa in empresas}
    except Exception as exc:
        logging.exception("Erro ao validar empresas antes do envio e-BEF: %s", exc)
        return jsonify({"error": "Não foi possível validar as empresas antes do envio."}), 500
    finally:
        db.close()

    historico = HistoricoEnviosEbef()
    resultados = []
    pendentes_envio = []

    for codigo in codigos:
        empresa = empresas_por_codigo.get(codigo)
        if not empresa:
            resultados.append(
                {
                    "codigo": codigo,
                    "status": "IGNORADO",
                    "motivo": "Empresa não localizada na lista de comunicação atual.",
                }
            )
            continue

        if not empresa.get("email_valido"):
            resultados.append(
                {
                    "codigo": codigo,
                    "razao_social": empresa.get("razao_social"),
                    "status": "IGNORADO",
                    "motivo": "Empresa sem e-mail válido na Domínio.",
                }
            )
            continue

        if empresa.get("ja_enviado") and not forcar_reenvio:
            resultados.append(
                {
                    "codigo": codigo,
                    "razao_social": empresa.get("razao_social"),
                    "email": empresa.get("email"),
                    "status": "JA_ENVIADO",
                    "motivo": "Comunicação já enviada com sucesso para este ano.",
                    "ultimo_envio_em": empresa.get("ultimo_envio_em"),
                }
            )
            continue

        pendentes_envio.append(empresa)

    if not pendentes_envio:
        return jsonify(
            {
                "resultados": resultados,
                "meta": {
                    "solicitadas": len(codigos),
                    "enviadas": 0,
                    "testes": 0,
                    "erros": 0,
                    "ignoradas": len(resultados),
                },
            }
        )

    try:
        servico_email = EmailEbefService()
        servico_email.conectar()
    except Exception as exc:
        erro_conexao = f"Falha ao conectar no SMTP: {exc}"
        logging.exception(erro_conexao)

        for empresa in pendentes_envio:
            historico.registrar(
                ano_apresentacao=ano_apresentacao,
                codigo_empresa=empresa["codigo"],
                cnpj=empresa["cnpj"],
                razao_social=empresa["razao_social"],
                email_destinatario=empresa["email"],
                assunto=getattr(servico_email, "assunto", "Comunicação e-BEF") if "servico_email" in locals() else "Comunicação e-BEF",
                anexo_nome=EmailEbefService.NOME_ANEXO,
                status="ERRO",
                erro=erro_conexao,
            )

        return jsonify({"error": erro_conexao}), 502

    try:
        for empresa in pendentes_envio:
            try:
                servico_email.enviar(
                    destinatario=empresa["email"],
                    razao_social=empresa["razao_social"],
                    cnpj=empresa["cnpj"],
                )

                status = "TESTE" if servico_email.modo_teste else "ENVIADO"
                destino_registrado = (
                    servico_email.destino_teste
                    if servico_email.modo_teste
                    else empresa["email"]
                )

                historico.registrar(
                    ano_apresentacao=ano_apresentacao,
                    codigo_empresa=empresa["codigo"],
                    cnpj=empresa["cnpj"],
                    razao_social=empresa["razao_social"],
                    email_destinatario=destino_registrado,
                    assunto=servico_email.assunto,
                    anexo_nome=servico_email.nome_anexo,
                    status=status,
                )

                resultados.append(
                    {
                        "codigo": empresa["codigo"],
                        "razao_social": empresa["razao_social"],
                        "email": empresa["email"],
                        "status": status,
                        "destino_teste": servico_email.destino_teste if servico_email.modo_teste else None,
                    }
                )
            except Exception as exc:
                erro = str(exc)
                logging.exception(
                    "Falha ao enviar e-BEF para empresa %s: %s",
                    empresa["codigo"],
                    erro,
                )
                historico.registrar(
                    ano_apresentacao=ano_apresentacao,
                    codigo_empresa=empresa["codigo"],
                    cnpj=empresa["cnpj"],
                    razao_social=empresa["razao_social"],
                    email_destinatario=empresa["email"],
                    assunto=servico_email.assunto,
                    anexo_nome=servico_email.nome_anexo,
                    status="ERRO",
                    erro=erro,
                )
                resultados.append(
                    {
                        "codigo": empresa["codigo"],
                        "razao_social": empresa["razao_social"],
                        "email": empresa["email"],
                        "status": "ERRO",
                        "erro": erro,
                    }
                )
    finally:
        servico_email.fechar()

    enviados = sum(1 for item in resultados if item.get("status") == "ENVIADO")
    testes = sum(1 for item in resultados if item.get("status") == "TESTE")
    erros = sum(1 for item in resultados if item.get("status") == "ERRO")
    ignorados = len(resultados) - enviados - testes - erros

    return jsonify(
        {
            "resultados": resultados,
            "meta": {
                "solicitadas": len(codigos),
                "enviadas": enviados,
                "testes": testes,
                "erros": erros,
                "ignoradas": ignorados,
                "modo_teste": servico_email.modo_teste,
                "destino_teste": servico_email.destino_teste if servico_email.modo_teste else None,
            },
        }
    )


if __name__ == "__main__":
    debug_ativo = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_ativo, port=5000)
