import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")


class HistoricoEnviosEbef:
    def __init__(self, caminho_banco=None):
        pasta_raiz = Path(__file__).resolve().parent.parent
        self.caminho_banco = Path(
            caminho_banco or pasta_raiz / "data" / "ebef_comunicacao.sqlite3"
        )
        self.caminho_banco.parent.mkdir(parents=True, exist_ok=True)
        self._garantir_estrutura()

    def _conectar(self):
        conexao = sqlite3.connect(self.caminho_banco, timeout=30)
        conexao.row_factory = sqlite3.Row
        return conexao

    def _garantir_estrutura(self):
        with self._conectar() as conexao:
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS envios_ebef (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ano_apresentacao INTEGER NOT NULL,
                    codigo_empresa TEXT NOT NULL,
                    cnpj TEXT NOT NULL,
                    razao_social TEXT NOT NULL,
                    email_destinatario TEXT NOT NULL,
                    assunto TEXT NOT NULL,
                    anexo_nome TEXT,
                    status TEXT NOT NULL,
                    erro TEXT,
                    tentativa_em TEXT NOT NULL
                )
                """
            )

            colunas = {
                linha["name"]
                for linha in conexao.execute("PRAGMA table_info(envios_ebef)").fetchall()
            }
            if "anexo_nome" not in colunas:
                conexao.execute("ALTER TABLE envios_ebef ADD COLUMN anexo_nome TEXT")

            conexao.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_envios_ebef_ano_codigo
                ON envios_ebef (ano_apresentacao, codigo_empresa, id DESC)
                """
            )
            conexao.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_envios_ebef_status
                ON envios_ebef (status)
                """
            )
            conexao.execute(
                """
                CREATE TABLE IF NOT EXISTS inclusoes_manuais_ebef (
                    ano_apresentacao INTEGER NOT NULL,
                    codigo_empresa TEXT NOT NULL,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    incluido_em TEXT NOT NULL,
                    atualizado_em TEXT NOT NULL,
                    PRIMARY KEY (ano_apresentacao, codigo_empresa)
                )
                """
            )
            conexao.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_inclusoes_manuais_ebef_ano_ativo
                ON inclusoes_manuais_ebef (ano_apresentacao, ativo)
                """
            )

    @staticmethod
    def _agora_iso():
        return datetime.now(FUSO_BRASIL).isoformat()

    def registrar(
        self,
        *,
        ano_apresentacao,
        codigo_empresa,
        cnpj,
        razao_social,
        email_destinatario,
        assunto,
        anexo_nome,
        status,
        erro=None,
    ):
        with self._conectar() as conexao:
            conexao.execute(
                """
                INSERT INTO envios_ebef (
                    ano_apresentacao,
                    codigo_empresa,
                    cnpj,
                    razao_social,
                    email_destinatario,
                    assunto,
                    anexo_nome,
                    status,
                    erro,
                    tentativa_em
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    int(ano_apresentacao),
                    str(codigo_empresa),
                    str(cnpj or ""),
                    str(razao_social or ""),
                    str(email_destinatario or ""),
                    str(assunto or ""),
                    str(anexo_nome or ""),
                    str(status),
                    str(erro) if erro else None,
                    self._agora_iso(),
                ),
            )

    def ja_enviado_com_sucesso(self, ano_apresentacao, codigo_empresa) -> bool:
        with self._conectar() as conexao:
            linha = conexao.execute(
                """
                SELECT 1
                FROM envios_ebef
                WHERE ano_apresentacao = ?
                  AND codigo_empresa = ?
                  AND status = 'ENVIADO'
                LIMIT 1
                """,
                (int(ano_apresentacao), str(codigo_empresa)),
            ).fetchone()
        return linha is not None

    def obter_resumo_empresas(self, ano_apresentacao, codigos_empresa) -> dict:
        codigos = [str(codigo) for codigo in codigos_empresa if codigo is not None]
        if not codigos:
            return {}

        placeholders = ",".join("?" for _ in codigos)
        parametros = [int(ano_apresentacao), *codigos]

        with self._conectar() as conexao:
            linhas = conexao.execute(
                f"""
                SELECT id, ano_apresentacao, codigo_empresa, email_destinatario,
                       status, erro, tentativa_em
                FROM envios_ebef
                WHERE ano_apresentacao = ?
                  AND codigo_empresa IN ({placeholders})
                ORDER BY id DESC
                """,
                parametros,
            ).fetchall()

        resumo = {}
        for linha in linhas:
            codigo = str(linha["codigo_empresa"])
            item = resumo.setdefault(
                codigo,
                {
                    "ja_enviado": False,
                    "ultimo_envio_em": None,
                    "ultimo_email_enviado": None,
                    "ultima_tentativa_status": None,
                    "ultima_tentativa_em": None,
                    "ultimo_erro": None,
                },
            )

            if item["ultima_tentativa_status"] is None:
                item["ultima_tentativa_status"] = linha["status"]
                item["ultima_tentativa_em"] = linha["tentativa_em"]
                item["ultimo_erro"] = linha["erro"]

            if linha["status"] == "ENVIADO" and not item["ja_enviado"]:
                item["ja_enviado"] = True
                item["ultimo_envio_em"] = linha["tentativa_em"]
                item["ultimo_email_enviado"] = linha["email_destinatario"]

        return resumo

    def listar_inclusoes_manuais(self, ano_apresentacao) -> list[str]:
        with self._conectar() as conexao:
            linhas = conexao.execute(
                """
                SELECT codigo_empresa
                FROM inclusoes_manuais_ebef
                WHERE ano_apresentacao = ? AND ativo = 1
                ORDER BY codigo_empresa
                """,
                (int(ano_apresentacao),),
            ).fetchall()
        return [str(linha["codigo_empresa"]) for linha in linhas]

    def incluir_empresa_manual(self, ano_apresentacao, codigo_empresa):
        agora = self._agora_iso()
        with self._conectar() as conexao:
            conexao.execute(
                """
                INSERT INTO inclusoes_manuais_ebef (
                    ano_apresentacao, codigo_empresa, ativo, incluido_em, atualizado_em
                )
                VALUES (?, ?, 1, ?, ?)
                ON CONFLICT(ano_apresentacao, codigo_empresa) DO UPDATE SET
                    ativo = 1,
                    atualizado_em = excluded.atualizado_em
                """,
                (int(ano_apresentacao), str(codigo_empresa), agora, agora),
            )

    def remover_empresa_manual(self, ano_apresentacao, codigo_empresa):
        with self._conectar() as conexao:
            cursor = conexao.execute(
                """
                UPDATE inclusoes_manuais_ebef
                SET ativo = 0, atualizado_em = ?
                WHERE ano_apresentacao = ? AND codigo_empresa = ? AND ativo = 1
                """,
                (self._agora_iso(), int(ano_apresentacao), str(codigo_empresa)),
            )
        return cursor.rowcount > 0
