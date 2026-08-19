import os
import re
import requests
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime


class ReceitaWsErro(Exception):
    """Erro controlado durante uma consulta à ReceitaWS."""

    def __init__(
        self,
        mensagem,
        http_status=None,
        retry_after=None,
    ):
        super().__init__(mensagem)
        self.http_status = http_status
        self.retry_after = retry_after


class ReceitaWsClient:
    def __init__(self):
        self.base_url = os.getenv(
            "RECEITAWS_BASE_URL",
            "https://receitaws.com.br/v1/cnpj",
        ).rstrip("/")
        self.timeout = int(os.getenv("RECEITAWS_TIMEOUT_SEGUNDOS", "70"))
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "Auditoria-EBEF/1.0",
            }
        )

    @staticmethod
    def normalizar_cnpj(cnpj) -> str:
        return re.sub(r"[^A-Z0-9]", "", str(cnpj or "").upper())

    @staticmethod
    def obter_retry_after(response):
        """
        Retorna em segundos o tempo solicitado pela API no cabeçalho Retry-After.

        O cabeçalho pode vir como uma quantidade de segundos ou como uma data HTTP.
        """
        valor = response.headers.get("Retry-After")

        if not valor:
            return None

        try:
            return max(1, int(float(valor)))
        except (TypeError, ValueError):
            pass

        try:
            data_limite = parsedate_to_datetime(valor)

            if data_limite.tzinfo is None:
                data_limite = data_limite.replace(tzinfo=timezone.utc)

            segundos = math.ceil(
                (data_limite - datetime.now(timezone.utc)).total_seconds()
            )

            return max(1, segundos)
        except (TypeError, ValueError, OverflowError):
            return None

    def consultar(self, cnpj) -> dict:
        cnpj_limpo = self.normalizar_cnpj(cnpj)
        if not re.fullmatch(r"[A-Z0-9]{12}[0-9]{2}", cnpj_limpo):
            raise ReceitaWsErro("CNPJ inválido para consulta na ReceitaWS.")

        try:
            response = self.session.get(
                f"{self.base_url}/{cnpj_limpo}",
                timeout=self.timeout,
            )
        except requests.Timeout as exc:
            raise ReceitaWsErro("Tempo limite excedido na ReceitaWS.") from exc
        except requests.RequestException as exc:
            raise ReceitaWsErro(f"Falha de comunicação com a ReceitaWS: {exc}") from exc

        if response.status_code == 429:
            raise ReceitaWsErro(
                "Limite de consultas da ReceitaWS excedido.",
                http_status=429,
                retry_after=self.obter_retry_after(response),
            )

        if response.status_code == 504:
            raise ReceitaWsErro(
                "A ReceitaWS não concluiu a consulta no prazo.",
                http_status=504,
            )
        if response.status_code != 200:
            raise ReceitaWsErro(
                f"ReceitaWS retornou HTTP {response.status_code}.",
                http_status=response.status_code,
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ReceitaWsErro("ReceitaWS retornou uma resposta JSON inválida.") from exc

        if not isinstance(payload, dict):
            raise ReceitaWsErro("Formato inesperado na resposta da ReceitaWS.")

        if str(payload.get("status", "")).upper() != "OK":
            mensagem = payload.get("message") or payload.get("mensagem")
            raise ReceitaWsErro(
                str(mensagem or "A ReceitaWS não localizou os dados do CNPJ."),
                http_status=200,
            )

        return payload
