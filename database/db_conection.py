import logging
import os
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
import pyodbc
from utils.sqlany_env import preparar_ambiente_sqlanywhere
from dotenv import load_dotenv
from utils.documentos import (
    normalizar_documento,
    transformar_lista_socios,
    validar_cnpj_numerico,
)


if os.name != "nt":
    try:
        preparar_ambiente_sqlanywhere()
    except Exception as exc:
        print(f"[SQLANY] Aviso: não foi possível preparar ambiente SQL Anywhere: {exc}")


PASTA_DATABASE = Path(__file__).resolve().parent
ARQUIVO_ENV_DATABASE = PASTA_DATABASE / ".env"
ARQUIVO_ENV_RAIZ = PASTA_DATABASE.parent / ".env"

if ARQUIVO_ENV_DATABASE.exists():
    load_dotenv(dotenv_path=ARQUIVO_ENV_DATABASE)
else:
    load_dotenv(dotenv_path=ARQUIVO_ENV_RAIZ)



class DatabaseConnection:
    ANO_INICIO_EBEF = 2026
    ANO_INICIO_FASE_78_MILHOES = 2027
    ANO_INICIO_FASE_4_8_MILHOES = 2028
    LIMITE_78_MILHOES = Decimal("78000000")
    LIMITE_4_8_MILHOES = Decimal("4800000")

    # Sociedades simples ou limitadas cujo enquadramento depende do QSA e da
    # receita bruta do ano anterior, conforme o faseamento do e-BEF.
    NATUREZAS_FASEADAS = {2062, 2070, 2089, 2232, 2240, 2259, 2267}
    NATUREZAS_LIMITADAS = {2062, 2240}

    # Dispensadas diretamente pela natureza jurídica. Os casos que dependem
    # de condições adicionais (fundos e entidades sem fins lucrativos) não
    # entram neste conjunto e são enviados para revisão manual.
    NATUREZAS_DISPENSADAS = {
        2011, 2038, 2046, 2135, 2194, 2275, 2283, 2305, 2313, 2321
    }

    @classmethod
    def obter_ano_apresentacao_padrao(cls) -> int:
        """Obtém o exercício padrão sem quebrar o .env utilizado anteriormente."""
        ano_apresentacao = os.getenv("EBEF_ANO_APRESENTACAO")
        if ano_apresentacao:
            return int(ano_apresentacao)

        # Compatibilidade: EBEF_ANO_REFERENCIA representa o ano da receita.
        ano_referencia = os.getenv("EBEF_ANO_REFERENCIA")
        if ano_referencia:
            return int(ano_referencia) + 1

        return max(cls.ANO_INICIO_EBEF, date.today().year)

    @classmethod
    def validar_ano_apresentacao(cls, valor) -> int:
        try:
            ano = int(valor)
        except (TypeError, ValueError) as exc:
            raise ValueError("Ano de apresentação inválido.") from exc

        ano_atual = date.today().year
        if ano < cls.ANO_INICIO_EBEF or ano > ano_atual:
            raise ValueError(
                f"O ano de apresentação deve estar entre "
                f"{cls.ANO_INICIO_EBEF} e {ano_atual}."
            )
        return ano

    def __init__(self, ano_apresentacao=None):
        self.host = os.getenv("DOMINIO_HOST")
        self.port = os.getenv("DOMINIO_PORT", "2638")
        self.dbname = os.getenv("DOMINIO_DB")
        self.user = os.getenv("DOMINIO_USER")
        self.password = os.getenv("DOMINIO_PASSWORD")
        self.engine = os.getenv("DOMINIO_ENGINE", "dominio")

        ano_solicitado = (
            self.obter_ano_apresentacao_padrao()
            if ano_apresentacao is None
            else ano_apresentacao
        )
        self.ano_apresentacao = self.validar_ano_apresentacao(ano_solicitado)
        self.ano_referencia = self.ano_apresentacao - 1
        self.codigo_maximo = int(os.getenv("EBEF_CODIGO_MAXIMO", "3526"))

        self.conn_str = (
            "DRIVER=SQL Anywhere 17;"
            f"UID={self.user};"
            f"PWD={self.password};"
            f"ENG={self.engine};"
            f"DBN={self.dbname};"
            f"LINKS=TCPIP(host={self.host}:{self.port});"
        )
        self.conn = None

    def connect(self):
        try:
            self.conn = pyodbc.connect(self.conn_str)
            return True
        except Exception as exc:
            logging.error("Erro ao conectar na Domínio: %s", exc)
            return False

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    @staticmethod
    def _valor_decimal(valor) -> Decimal:
        if valor is None:
            return Decimal("0")
        if isinstance(valor, Decimal):
            return valor
        return Decimal(str(valor))

    @staticmethod
    def _codigo_natureza_inteiro(valor):
        if valor is None:
            return None
        somente_numeros = re.sub(r"\D", "", str(valor))
        return int(somente_numeros) if somente_numeros else None

    @classmethod
    def _natureza_dispensa_direta(cls, codigo) -> bool:
        if codigo is None:
            return False
        return (
            1015 <= codigo <= 1341
            or codigo in cls.NATUREZAS_DISPENSADAS
            or 4014 <= codigo <= 4120
            or 5010 <= codigo <= 5037
        )

    @staticmethod
    def _chave_raiz(cnpj: str, codigo_empresa) -> str:
        if len(cnpj) == 14:
            return cnpj[:8]
        return f"INVALIDO-{codigo_empresa}"

    def _consolidar_por_raiz(self, linhas: list) -> list:
        grupos = {}

        for linha in linhas:
            cnpj = normalizar_documento(linha.get("cnpj"))
            chave = self._chave_raiz(cnpj, linha.get("codigo"))
            grupos.setdefault(chave, []).append({**linha, "cnpj": cnpj})

        consolidadas = []
        for raiz, estabelecimentos_brutos in grupos.items():
            # /0001 é usado somente para escolher qual cadastro será exibido.
            # A obrigação é consolidada pela raiz e não depende dessa suposição.
            estabelecimentos_brutos.sort(
                key=lambda item: (
                    0 if item["cnpj"][8:12] == "0001" else 1,
                    item["codigo"],
                )
            )
            principal = estabelecimentos_brutos[0]

            listas_socios = [
                str(item["lista_socios"])
                for item in estabelecimentos_brutos
                if item.get("lista_socios")
            ]
            faturamento_total = sum(
                (self._valor_decimal(item.get("faturamento")) for item in estabelecimentos_brutos),
                Decimal("0"),
            )

            codigos_natureza = {
                self._codigo_natureza_inteiro(item.get("codigo_natureza"))
                for item in estabelecimentos_brutos
                if item.get("codigo_natureza") is not None
            }
            descricoes_natureza = {
                str(item["natureza_juridica"]).strip()
                for item in estabelecimentos_brutos
                if item.get("natureza_juridica")
            }

            estabelecimentos = [
                {
                    "codigo": item["codigo"],
                    "razao_social": item["razao_social"],
                    "cnpj": item["cnpj"],
                    "ordem_cnpj": item["cnpj"][8:12] if len(item["cnpj"]) == 14 else "",
                    "cadastro_exibido": item is principal,
                }
                for item in estabelecimentos_brutos
            ]

            empresa = {
                "codigo": principal["codigo"],
                "codigos_empresa": [item["codigo"] for item in estabelecimentos_brutos],
                "razao_social": principal["razao_social"],
                "cnpj": principal["cnpj"],
                "cnpj_raiz": raiz if not raiz.startswith("INVALIDO-") else "",
                "codigo_natureza": next(iter(codigos_natureza), None),
                "natureza_juridica": next(iter(descricoes_natureza), None),
                "natureza_inconsistente": (
                    len(codigos_natureza) > 1 or len(descricoes_natureza) > 1
                ),
                "lista_socios": " | ".join(listas_socios),
                "faturamento": faturamento_total,
                "estabelecimentos": estabelecimentos,
                "qtd_estabelecimentos": len(estabelecimentos),
                "qtd_filiais_agregadas": max(0, len(estabelecimentos) - 1),
            }
            consolidadas.append(empresa)

        return consolidadas

    def _classificar_faseamento_por_receita(
        self,
        faturamento_decimal: Decimal,
    ):
        """Aplica as etapas publicadas para sociedades simples/limitadas sem PJ."""
        if faturamento_decimal <= self.LIMITE_4_8_MILHOES:
            return (
                "DISPENSA_PROVAVEL",
                "Dispensa por QSA e receita — validar ECF",
                (
                    f"Dispensa provável em {self.ano_apresentacao}: não há sócio PJ "
                    "no QSA atual e a receita fiscal estimada não ultrapassa "
                    "R$ 4,8 milhões. Confirmar a receita bruta oficial na ECF "
                    f"referente a {self.ano_referencia}."
                ),
                None,
            )

        if faturamento_decimal > self.LIMITE_78_MILHOES:
            ano_inicio = self.ANO_INICIO_FASE_78_MILHOES
            faixa_receita = "acima de R$ 78 milhões"
        else:
            ano_inicio = self.ANO_INICIO_FASE_4_8_MILHOES
            faixa_receita = "acima de R$ 4,8 milhões e até R$ 78 milhões"

        if self.ano_apresentacao >= ano_inicio:
            return (
                "OBRIGADA",
                f"Obrigação por receita — etapa vigente desde {ano_inicio}",
                (
                    f"Obrigada em {self.ano_apresentacao}: não há sócio PJ no QSA "
                    f"atual, mas a receita fiscal estimada de {self.ano_referencia} "
                    f"está {faixa_receita}. Esta etapa do faseamento vigora desde "
                    f"{ano_inicio}. Confirmar a receita bruta oficial na ECF."
                ),
                ano_inicio,
            )

        return (
            "FASEAMENTO_FUTURO",
            f"Faseamento futuro — reavaliar em {ano_inicio}",
            (
                f"No ano de apresentação {self.ano_apresentacao}, esta faixa de "
                f"receita ainda não gera obrigação pelo faseamento. A etapa começa "
                f"em {ano_inicio}; o enquadramento deverá ser recalculado naquele "
                "exercício com a receita do respectivo ano anterior declarada na ECF."
            ),
            ano_inicio,
        )

    def _classificar_empresa(self, empresa: dict) -> dict:
        faturamento_decimal = self._valor_decimal(empresa.get("faturamento"))
        socios = transformar_lista_socios(empresa.get("lista_socios"))

        socios_pj = [
            socio
            for socio in socios
            if socio["tipo"] == "PJ" and socio["valido"] is not False
        ]
        documentos_inconsistentes = [
            socio for socio in socios if socio["valido"] is False
        ]

        cnpj = normalizar_documento(empresa.get("cnpj"))
        if len(cnpj) == 14 and cnpj.isdigit():
            cnpj_valido = validar_cnpj_numerico(cnpj)
        elif len(cnpj) == 14 and cnpj.isalnum():
            cnpj_valido = None
        else:
            cnpj_valido = False

        codigo_natureza = self._codigo_natureza_inteiro(
            empresa.get("codigo_natureza")
        )
        natureza_juridica = empresa.get("natureza_juridica")
        natureza_inconsistente = empresa.get("natureza_inconsistente", False)
        faseada = codigo_natureza in self.NATUREZAS_FASEADAS
        limitada = codigo_natureza in self.NATUREZAS_LIMITADAS
        ano_inicio_regra = None

        if cnpj_valido is False:
            status = "DADOS_INCONSISTENTES"
            motivo_curto = "CNPJ da empresa inválido"
            diagnostico = (
                "Cadastro inconsistente: o CNPJ da empresa não passou na validação. "
                "Corrija ou confirme o cadastro antes de concluir a auditoria do e-BEF."
            )
        elif natureza_inconsistente:
            status = "DADOS_INCONSISTENTES"
            motivo_curto = "Natureza divergente entre estabelecimentos"
            diagnostico = (
                "Os estabelecimentos agrupados pela mesma raiz possuem naturezas "
                "jurídicas divergentes na Domínio. Revise os cadastros antes de concluir."
            )
        elif codigo_natureza is None or not natureza_juridica:
            status = "DADOS_INSUFICIENTES"
            motivo_curto = "Natureza jurídica não cadastrada"
            diagnostico = (
                "A empresa não possui natureza jurídica vinculada na Domínio. "
                "Preencha ou corrija o cadastro para concluir a auditoria."
            )
        elif self._natureza_dispensa_direta(codigo_natureza):
            status = "DISPENSADA"
            motivo_curto = f"Dispensa pela natureza {codigo_natureza}"
            diagnostico = (
                f"Dispensada do e-BEF pela natureza jurídica {codigo_natureza} - "
                f"{natureza_juridica}."
            )
        elif codigo_natureza == 2224:
            status = "REVISAO_MANUAL"
            motivo_curto = "Fundo: validar condição de dispensa"
            diagnostico = (
                "Clube ou fundo de investimento: a dispensa depende da regulamentação "
                "pela CVM e da prestação das informações exigidas pela Receita Federal."
            )
        elif 3034 <= codigo_natureza <= 3999:
            status = "REVISAO_MANUAL"
            motivo_curto = "Entidade sem fins lucrativos"
            diagnostico = (
                "Entidade sem fins lucrativos: validar se recebe verbas públicas ou "
                "atua como administradora fiduciária/gestora de ativos de terceiros."
            )
        elif codigo_natureza == 2127:
            status = "OBRIGADA"
            ano_inicio_regra = self.ANO_INICIO_EBEF

            if not socios:
                motivo_curto = "SCP obrigada — participantes pendentes"
                diagnostico = (
                    f"Obrigada em {self.ano_apresentacao}: Sociedade em Conta de "
                    "Participação. "
                    "Não foram localizados o sócio ostensivo e os participantes "
                    "no quadro específico da SCP no Domínio. O cadastro deve ser "
                    "complementado para identificar os beneficiários finais."
                )
            elif documentos_inconsistentes:
                motivo_curto = "SCP obrigada — documentos pendentes"
                diagnostico = (
                    f"Obrigada em {self.ano_apresentacao}: Sociedade em Conta de "
                    "Participação. "
                    "O quadro específico da SCP foi localizado, mas há participante "
                    "com CPF ou CNPJ ausente ou inválido. Tanto o sócio ostensivo "
                    "quanto os participantes devem ser considerados, "
                    "independentemente do percentual."
                )
            else:
                motivo_curto = f"SCP com {len(socios)} participante(s)"
                diagnostico = (
                    f"Obrigada em {self.ano_apresentacao}: Sociedade em Conta de "
                    "Participação com "
                    f"{len(socios)} participante(s) localizado(s). Tanto o sócio "
                    "ostensivo quanto os participantes devem ser considerados, "
                    "independentemente do percentual de participação."
                )
        elif faseada and documentos_inconsistentes:
            status = "DADOS_INCONSISTENTES"
            motivo_curto = "Documento societário inconsistente"
            diagnostico = (
                "Há CPF/CNPJ ausente ou inválido no quadro societário. Corrija ou "
                "confirme os documentos antes de concluir se existem sócios PJ."
            )
        elif faseada and not socios:
            status = "DADOS_INSUFICIENTES"
            motivo_curto = "QSA não localizado"
            diagnostico = (
                "Não foi localizado QSA atual na Domínio. Para esta natureza, o QSA é "
                "necessário para validar o faseamento ou a obrigação no ano "
                f"selecionado ({self.ano_apresentacao})."
            )
        elif faseada and socios_pj and limitada:
            status = "OBRIGADA"
            ano_inicio_regra = self.ANO_INICIO_EBEF
            motivo_curto = f"Limitada com {len(socios_pj)} sócio(s) PJ"
            diagnostico = (
                f"Obrigada em {self.ano_apresentacao}: {natureza_juridica} com "
                f"{len(socios_pj)} "
                "sócio(s) pessoa jurídica no QSA atual."
            )
        elif faseada and socios_pj:
            status = "REVISAO_MANUAL"
            motivo_curto = "Sociedade faseada com sócio PJ"
            diagnostico = (
                "Há sócio PJ no QSA atual. A dispensa por faturamento exige ausência "
                "de pessoa jurídica no QSA; valide o enquadramento desta natureza."
            )
        elif faseada:
            (
                status,
                motivo_curto,
                diagnostico,
                ano_inicio_regra,
            ) = self._classificar_faseamento_por_receita(
                faturamento_decimal
            )
        else:
            status = "OBRIGADA"
            ano_inicio_regra = self.ANO_INICIO_EBEF
            motivo_curto = f"Obrigação pela natureza {codigo_natureza}"
            diagnostico = (
                f"Obrigada em {self.ano_apresentacao} pela natureza jurídica "
                f"{codigo_natureza} - "
                f"{natureza_juridica}, não abrangida pelas dispensas ou pelo faseamento."
            )

        empresa.update(
            {
                "cnpj": cnpj,
                "cnpj_valido": cnpj_valido,
                "codigo_natureza": codigo_natureza,
                "natureza_juridica": natureza_juridica,
                "socios": socios,
                "qtd_socios": len(socios),
                "qtd_socios_pj": len(socios_pj),
                "qtd_documentos_inconsistentes": len(documentos_inconsistentes),
                "faturamento": float(faturamento_decimal),
                "tem_movimento": faturamento_decimal > 0,
                "ano_apresentacao": self.ano_apresentacao,
                "ano_referencia": self.ano_referencia,
                "ano_inicio_regra": ano_inicio_regra,
                "status_codigo": status,
                "motivo_curto": motivo_curto,
                "diagnostico": diagnostico,
                "conclusao_definitiva": status in {"OBRIGADA", "DISPENSADA"},
            }
        )
        return empresa

    def get_relatorio_ebef(self) -> list:
        """Busca, consolida e classifica os dados de auditoria do e-BEF."""
        if not self.conn:
            logging.error(
                "Conexão não estabelecida antes de chamar get_relatorio_ebef."
            )
            return []

        query = """
        SELECT
            emp.codi_emp AS codigo,
            emp.nome_emp AS razao_social,
            emp.cgce_emp AS cnpj,
            emp.njud_emp AS codigo_natureza,
            nat.descricao AS natureza_juridica,

            CASE
                -- Para SCP, usa o quadro específico vinculado pelo CNPJ da SCP.
                WHEN emp.njud_emp = 2127 THEN
                    (
                        SELECT LIST(
                            COALESCE(soc_scp.nome, 'PARTICIPANTE SEM CADASTRO')
                            ||
                            CASE
                                WHEN quadro.participacao IS NOT NULL
                                    THEN ' - Participação: '
                                         || quadro.participacao
                                         || '%'
                                ELSE ''
                            END
                            || ' ('
                            || COALESCE(soc_scp.inscricao, '')
                            || ')',
                            ' | '
                        )
                        FROM "bethadba"."gescp" scp
                        INNER JOIN "bethadba"."gescp_quadro_societario_socio" quadro
                            ON quadro.codi_emp = scp.codi_emp
                           AND quadro.i_scp = scp.i_scp
                        LEFT JOIN "bethadba"."gesocios" soc_scp
                            ON soc_scp.i_socio = quadro.i_socio
                        WHERE scp.situacao = 1
                          AND (
                                scp.data_inativo IS NULL
                                OR scp.data_inativo > CURRENT DATE
                              )
                          AND REPLACE(
                                REPLACE(
                                    REPLACE(
                                        REPLACE(TRIM(scp.CNPJ_SCP), '.', ''),
                                        '/', ''
                                    ),
                                    '-', ''
                                ),
                                ' ', ''
                              )
                              =
                              REPLACE(
                                REPLACE(
                                    REPLACE(
                                        REPLACE(TRIM(emp.cgce_emp), '.', ''),
                                        '/', ''
                                    ),
                                    '-', ''
                                ),
                                ' ', ''
                              )
                    )
                -- Para as demais empresas, mantém o QSA normal.
                ELSE
                    (
                        SELECT LIST(
                            soc.nome
                            || ' ('
                            || COALESCE(soc.inscricao, '')
                            || ')',
                            ' | '
                        )
                        FROM "bethadba"."gequadrosocietario_socios" q_soc
                        INNER JOIN "bethadba"."gesocios" soc
                            ON q_soc.i_socio = soc.i_socio
                        WHERE q_soc.codi_emp = emp.codi_emp
                          AND (
                                q_soc.data_saida IS NULL
                                OR q_soc.data_saida > CURRENT DATE
                              )
                    )
            END AS lista_socios,

            (
                COALESCE(
                    (SELECT SUM(sai.vcon_sai)
                     FROM "bethadba"."efsaidas" sai
                     WHERE sai.codi_emp = emp.codi_emp
                       AND YEAR(sai.DATA_SAIDA) = ?),
                    0
                )
                +
                COALESCE(
                    (SELECT SUM(ser.VALOR_SERVICOS_SER)
                     FROM "bethadba"."efservicos" ser
                     WHERE ser.codi_emp = emp.codi_emp
                       AND YEAR(ser.DATA_SERVICO) = ?),
                    0
                )
            ) AS faturamento

        FROM "bethadba"."geempre" emp
        LEFT JOIN "bethadba"."genatjuridica" nat
          ON nat.codigo = emp.njud_emp
        WHERE emp.cgce_emp IS NOT NULL
          -- Considera somente clientes atualmente ativos no Domínio.
          -- I (inativa) e B não participam da auditoria nem da consolidação.
          AND emp.stat_emp = 'A'
          AND TRIM(emp.cgce_emp) NOT IN ('00000000000000', '')
          -- A E-BEF é apurada por pessoa jurídica. A tabela geempre também
          -- contém pessoas físicas; por isso, mantém somente inscrições com
          -- 14 posições após remover a pontuação do CNPJ.
          AND LENGTH(
                REPLACE(
                    REPLACE(
                        REPLACE(
                            REPLACE(TRIM(emp.cgce_emp), '.', ''),
                            '/', ''
                        ),
                        '-', ''
                    ),
                    ' ', ''
                )
              ) = 14

          -- Mantém a matriz e suas filiais ativas somente quando também
          -- existe uma matriz /0001 ativa para a mesma raiz de CNPJ.
          AND EXISTS (
                SELECT 1
                FROM "bethadba"."geempre" matriz
                WHERE matriz.stat_emp = 'A'
                  AND matriz.cgce_emp IS NOT NULL
                  AND LENGTH(
                        REPLACE(
                            REPLACE(
                                REPLACE(
                                    REPLACE(TRIM(matriz.cgce_emp), '.', ''),
                                    '/', ''
                                ),
                                '-', ''
                            ),
                            ' ', ''
                        )
                      ) = 14
                  AND SUBSTRING(
                        REPLACE(
                            REPLACE(
                                REPLACE(
                                    REPLACE(TRIM(matriz.cgce_emp), '.', ''),
                                    '/', ''
                                ),
                                '-', ''
                            ),
                            ' ', ''
                        ),
                        9,
                        4
                      ) = '0001'
                  AND SUBSTRING(
                        REPLACE(
                            REPLACE(
                                REPLACE(
                                    REPLACE(TRIM(matriz.cgce_emp), '.', ''),
                                    '/', ''
                                ),
                                '-', ''
                            ),
                            ' ', ''
                        ),
                        1,
                        8
                      )
                      =
                      SUBSTRING(
                        REPLACE(
                            REPLACE(
                                REPLACE(
                                    REPLACE(TRIM(emp.cgce_emp), '.', ''),
                                    '/', ''
                                ),
                                '-', ''
                            ),
                            ' ', ''
                        ),
                        1,
                        8
                      )
              )
          AND emp.nome_emp NOT LIKE '%LIBERADO%'
          AND emp.nome_emp <> '.'
          AND emp.codi_emp <= ?
        ORDER BY emp.codi_emp
        """

        cursor = self.conn.cursor()
        try:
            cursor.execute(
                query,
                self.ano_referencia,
                self.ano_referencia,
                self.codigo_maximo,
            )
            columns = [column[0] for column in cursor.description]
            linhas = [dict(zip(columns, row)) for row in cursor.fetchall()]
            resultados = [
                self._classificar_empresa(empresa)
                for empresa in self._consolidar_por_raiz(linhas)
            ]

            ordem_status = {
                "OBRIGADA": 1,
                "DADOS_INCONSISTENTES": 2,
                "DADOS_INSUFICIENTES": 3,
                "REVISAO_MANUAL": 4,
                "FASEAMENTO_FUTURO": 5,
                "DISPENSA_PROVAVEL": 6,
                "DISPENSADA": 7,
            }
            resultados.sort(
                key=lambda item: (
                    ordem_status.get(item["status_codigo"], 99),
                    item["codigo"],
                )
            )
            return resultados
        except Exception as exc:
            logging.exception("Erro ao buscar dados do E-BEF: %s", exc)
            return []
        finally:
            cursor.close()
