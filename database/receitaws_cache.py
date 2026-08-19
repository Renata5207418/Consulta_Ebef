import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path


PAISES_BRASIL = {"BR", "BRA", "BRASIL", "BRAZIL"}


def agora_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalizar_texto(valor) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    texto = re.sub(r"[^A-Z0-9]+", " ", texto.upper())
    return " ".join(texto.split())


def normalizar_cnpj(valor) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(valor or "").upper())


def pais_internacional(pais) -> bool:
    pais_normalizado = normalizar_texto(pais).replace(" ", "")
    if not pais_normalizado:
        return False

    # A ReceitaWS pode devolver apenas o nome, a sigla ou um valor composto,
    # como "105 - BRASIL". Nenhuma dessas variações deve virar exterior.
    if (
        pais_normalizado in PAISES_BRASIL
        or pais_normalizado.endswith("BRASIL")
        or pais_normalizado.endswith("BRAZIL")
    ):
        return False
    return True


def analisar_origem_qsa(qsa: list) -> dict:
    if not qsa:
        return {
            "status": "QSA_VAZIO",
            "possui_socio_internacional": False,
            "paises": [],
        }

    paises = []
    possui_internacional = False
    for socio in qsa:
        pais = str(socio.get("pais_origem") or "").strip()
        if not pais:
            continue
        if pais not in paises:
            paises.append(pais)
        if pais_internacional(pais):
            possui_internacional = True

    if possui_internacional:
        status = "INTERNACIONAL"
    elif paises:
        status = "BRASIL_INFORMADO"
    else:
        status = "NAO_INFORMADO"

    return {
        "status": status,
        "possui_socio_internacional": possui_internacional,
        "paises": paises,
    }


class ReceitaWsCache:
    def __init__(self, caminho_banco=None):
        projeto = Path(__file__).resolve().parent.parent
        caminho_padrao = projeto / "data" / "ebef_receitaws.sqlite3"
        self.caminho_banco = Path(
            caminho_banco or os.getenv("RECEITAWS_DB_PATH", str(caminho_padrao))
        ).expanduser().resolve()
        self.caminho_banco.parent.mkdir(parents=True, exist_ok=True)
        self._inicializar()

    def _conectar(self):
        conn = sqlite3.connect(self.caminho_banco, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _inicializar(self):
        with self._conectar() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS receitaws_empresa (
                    cnpj TEXT PRIMARY KEY,
                    status_consulta TEXT NOT NULL DEFAULT 'NAO_CONSULTADO',
                    http_status INTEGER,
                    erro TEXT,
                    tentativas INTEGER NOT NULL DEFAULT 0,
                    ultima_tentativa_em TEXT,
                    ultima_consulta_em TEXT,
                    ultima_atualizacao_fonte TEXT,
                    tipo TEXT,
                    nome TEXT,
                    natureza_juridica TEXT,
                    situacao TEXT,
                    billing_database INTEGER,
                    origem_qsa_status TEXT,
                    possui_socio_internacional INTEGER NOT NULL DEFAULT 0,
                    paises_socios_json TEXT NOT NULL DEFAULT '[]',
                    hash_conteudo TEXT,
                    raw_json TEXT
                );

                CREATE TABLE IF NOT EXISTS receitaws_qsa (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cnpj_empresa TEXT NOT NULL,
                    ordem INTEGER NOT NULL,
                    nome TEXT,
                    nome_normalizado TEXT,
                    qualificacao TEXT,
                    pais_origem TEXT,
                    pais_origem_normalizado TEXT,
                    nome_rep_legal TEXT,
                    qual_rep_legal TEXT,
                    FOREIGN KEY (cnpj_empresa)
                        REFERENCES receitaws_empresa(cnpj)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_receitaws_qsa_cnpj
                    ON receitaws_qsa(cnpj_empresa);
                CREATE INDEX IF NOT EXISTS idx_receitaws_empresa_consulta
                    ON receitaws_empresa(ultima_consulta_em);
                """
            )

    def salvar_sucesso(self, cnpj, payload: dict):
        cnpj_limpo = normalizar_cnpj(cnpj)
        qsa = payload.get("qsa") if isinstance(payload.get("qsa"), list) else []
        analise = analisar_origem_qsa(qsa)
        raw_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        hash_conteudo = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
        consultado_em = agora_utc_iso()
        billing = payload.get("billing") if isinstance(payload.get("billing"), dict) else {}

        with self._conectar() as conn:
            conn.execute(
                """
                INSERT INTO receitaws_empresa (
                    cnpj, status_consulta, http_status, erro, tentativas,
                    ultima_tentativa_em, ultima_consulta_em,
                    ultima_atualizacao_fonte, tipo, nome, natureza_juridica,
                    situacao, billing_database, origem_qsa_status,
                    possui_socio_internacional, paises_socios_json,
                    hash_conteudo, raw_json
                ) VALUES (?, 'OK', 200, NULL, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cnpj) DO UPDATE SET
                    status_consulta = 'OK',
                    http_status = 200,
                    erro = NULL,
                    tentativas = 0,
                    ultima_tentativa_em = excluded.ultima_tentativa_em,
                    ultima_consulta_em = excluded.ultima_consulta_em,
                    ultima_atualizacao_fonte = excluded.ultima_atualizacao_fonte,
                    tipo = excluded.tipo,
                    nome = excluded.nome,
                    natureza_juridica = excluded.natureza_juridica,
                    situacao = excluded.situacao,
                    billing_database = excluded.billing_database,
                    origem_qsa_status = excluded.origem_qsa_status,
                    possui_socio_internacional = excluded.possui_socio_internacional,
                    paises_socios_json = excluded.paises_socios_json,
                    hash_conteudo = excluded.hash_conteudo,
                    raw_json = excluded.raw_json
                """,
                (
                    cnpj_limpo,
                    consultado_em,
                    consultado_em,
                    payload.get("ultima_atualizacao"),
                    payload.get("tipo"),
                    payload.get("nome"),
                    payload.get("natureza_juridica"),
                    payload.get("situacao"),
                    1 if billing.get("database") is True else 0,
                    analise["status"],
                    1 if analise["possui_socio_internacional"] else 0,
                    json.dumps(analise["paises"], ensure_ascii=False),
                    hash_conteudo,
                    raw_json,
                ),
            )
            conn.execute(
                "DELETE FROM receitaws_qsa WHERE cnpj_empresa = ?",
                (cnpj_limpo,),
            )
            for ordem, socio in enumerate(qsa, start=1):
                conn.execute(
                    """
                    INSERT INTO receitaws_qsa (
                        cnpj_empresa, ordem, nome, nome_normalizado,
                        qualificacao, pais_origem, pais_origem_normalizado,
                        nome_rep_legal, qual_rep_legal
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cnpj_limpo,
                        ordem,
                        socio.get("nome"),
                        normalizar_texto(socio.get("nome")),
                        socio.get("qual"),
                        socio.get("pais_origem"),
                        normalizar_texto(socio.get("pais_origem")),
                        socio.get("nome_rep_legal"),
                        socio.get("qual_rep_legal"),
                    ),
                )

    def salvar_erro(self, cnpj, mensagem, http_status=None):
        cnpj_limpo = normalizar_cnpj(cnpj)
        tentativa_em = agora_utc_iso()
        with self._conectar() as conn:
            conn.execute(
                """
                INSERT INTO receitaws_empresa (
                    cnpj, status_consulta, http_status, erro, tentativas,
                    ultima_tentativa_em
                ) VALUES (?, 'ERRO', ?, ?, 1, ?)
                ON CONFLICT(cnpj) DO UPDATE SET
                    status_consulta = 'ERRO',
                    http_status = excluded.http_status,
                    erro = excluded.erro,
                    tentativas = receitaws_empresa.tentativas + 1,
                    ultima_tentativa_em = excluded.ultima_tentativa_em
                """,
                (cnpj_limpo, http_status, str(mensagem), tentativa_em),
            )

    def selecionar_pendentes(self, empresas: list, ttl_dias=30, limite=30) -> list:
        candidatos = []
        vistos = set()
        for empresa in empresas:
            cnpj = normalizar_cnpj(empresa.get("cnpj"))
            if len(cnpj) != 14 or cnpj in vistos:
                continue
            vistos.add(cnpj)
            candidatos.append(
                {
                    "cnpj": cnpj,
                    "codigo": empresa.get("codigo"),
                    "razao_social": empresa.get("razao_social"),
                }
            )

        dados = self._obter_empresas_por_cnpj([item["cnpj"] for item in candidatos])
        corte = datetime.now(timezone.utc) - timedelta(days=int(ttl_dias))
        pendentes = []
        for item in candidatos:
            registro = dados.get(item["cnpj"])
            if not registro:
                pendentes.append(item)
                continue

            ultima_consulta = registro.get("ultima_consulta_em")
            if registro.get("status_consulta") != "OK" or not ultima_consulta:
                pendentes.append(item)
                continue

            try:
                ultima_data = datetime.fromisoformat(ultima_consulta)
            except (TypeError, ValueError):
                pendentes.append(item)
                continue

            if ultima_data < corte:
                pendentes.append(item)

        pendentes.sort(
            key=lambda item: (
                0 if item["cnpj"] not in dados else 1,
                item.get("codigo") or 0,
            )
        )
        if limite is None:
            return pendentes
        return pendentes[: max(0, int(limite))]

    def _obter_empresas_por_cnpj(self, cnpjs: list) -> dict:
        resultado = {}
        if not cnpjs:
            return resultado

        with self._conectar() as conn:
            for inicio in range(0, len(cnpjs), 500):
                lote = cnpjs[inicio: inicio + 500]
                placeholders = ",".join("?" for _ in lote)
                rows = conn.execute(
                    f"SELECT * FROM receitaws_empresa WHERE cnpj IN ({placeholders})",
                    lote,
                ).fetchall()
                for row in rows:
                    resultado[row["cnpj"]] = dict(row)
        return resultado

    def _obter_qsa_por_cnpj(self, cnpjs: list) -> dict:
        resultado = {cnpj: [] for cnpj in cnpjs}
        if not cnpjs:
            return resultado

        with self._conectar() as conn:
            for inicio in range(0, len(cnpjs), 500):
                lote = cnpjs[inicio: inicio + 500]
                placeholders = ",".join("?" for _ in lote)
                rows = conn.execute(
                    f"""
                    SELECT * FROM receitaws_qsa
                    WHERE cnpj_empresa IN ({placeholders})
                    ORDER BY cnpj_empresa, ordem
                    """,
                    lote,
                ).fetchall()
                for row in rows:
                    socio = dict(row)
                    socio["internacional"] = pais_internacional(socio.get("pais_origem"))
                    resultado.setdefault(row["cnpj_empresa"], []).append(socio)
        return resultado

    def enriquecer_empresas(self, empresas: list) -> list:
        cnpjs = [normalizar_cnpj(empresa.get("cnpj")) for empresa in empresas]
        registros = self._obter_empresas_por_cnpj(cnpjs)
        qsa_por_cnpj = self._obter_qsa_por_cnpj(cnpjs)

        for empresa in empresas:
            cnpj = normalizar_cnpj(empresa.get("cnpj"))
            registro = registros.get(cnpj)
            if not registro:
                empresa["receitaws"] = {
                    "disponivel": False,
                    "status_consulta": "NAO_CONSULTADO",
                    "origem_qsa_status": "NAO_CONSULTADO",
                    "possui_socio_internacional": False,
                    "qsa": [],
                    "paises": [],
                }
                continue

            qsa = qsa_por_cnpj.get(cnpj, [])
            try:
                paises = json.loads(registro.get("paises_socios_json") or "[]")
            except (TypeError, ValueError):
                paises = []

            possui_dados_validos = bool(registro.get("ultima_consulta_em"))
            origem_qsa_status = registro.get("origem_qsa_status")
            if not origem_qsa_status:
                origem_qsa_status = (
                    "ERRO"
                    if registro.get("status_consulta") == "ERRO"
                    else "NAO_CONSULTADO"
                )

            empresa["receitaws"] = {
                "disponivel": possui_dados_validos,
                "status_consulta": registro.get("status_consulta"),
                "http_status": registro.get("http_status"),
                "erro": registro.get("erro"),
                "consultado_em": registro.get("ultima_consulta_em"),
                "ultima_tentativa_em": registro.get("ultima_tentativa_em"),
                "ultima_atualizacao_fonte": registro.get("ultima_atualizacao_fonte"),
                "dados_em_cache": registro.get("billing_database") == 1,
                "tipo": registro.get("tipo"),
                "situacao": registro.get("situacao"),
                "origem_qsa_status": origem_qsa_status,
                "possui_socio_internacional": registro.get("possui_socio_internacional") == 1,
                "paises": paises,
                "qsa": qsa,
            }

            qsa_por_nome = {}
            for socio_receita in qsa:
                nome = socio_receita.get("nome_normalizado")
                if nome:
                    qsa_por_nome.setdefault(nome, []).append(socio_receita)

            for socio_dominio in empresa.get("socios") or []:
                correspondencias = qsa_por_nome.get(
                    normalizar_texto(socio_dominio.get("nome")),
                    [],
                )
                if len(correspondencias) == 1:
                    socio_receita = correspondencias[0]
                    socio_dominio["correspondencia_receitaws"] = True
                    socio_dominio["pais_origem_receitaws"] = socio_receita.get("pais_origem")
                    socio_dominio["internacional_receitaws"] = socio_receita.get("internacional", False)
                    socio_dominio["qualificacao_receitaws"] = socio_receita.get("qualificacao")
                else:
                    socio_dominio["correspondencia_receitaws"] = False
                    socio_dominio["pais_origem_receitaws"] = None
                    socio_dominio["internacional_receitaws"] = False
                    socio_dominio["qualificacao_receitaws"] = None

        return empresas
