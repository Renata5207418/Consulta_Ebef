import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, render_template, request
from database.db_conection import DatabaseConnection
from database.receitaws_cache import ReceitaWsCache


app = Flask(__name__)


def obter_ano_apresentacao_padrao() -> int:
    try:
        return DatabaseConnection.validar_ano_apresentacao(
            DatabaseConnection.obter_ano_apresentacao_padrao()
        )
    except ValueError as exc:
        ano_atual = datetime.now(ZoneInfo("America/Sao_Paulo")).year
        logging.warning(
            "Ano padrão do e-BEF inválido no .env (%s). Usando %s.",
            exc,
            ano_atual,
        )
        return max(DatabaseConnection.ANO_INICIO_EBEF, ano_atual)


@app.route("/")
def index():
    ano_atual = datetime.now(ZoneInfo("America/Sao_Paulo")).year
    ano_padrao = obter_ano_apresentacao_padrao()
    anos_disponiveis = list(
        range(DatabaseConnection.ANO_INICIO_EBEF, ano_atual + 1)
    )
    return render_template(
        "index.html",
        anos_disponiveis=anos_disponiveis,
        ano_apresentacao_padrao=ano_padrao,
    )


@app.route("/api/ebef")
def api_ebef():
    ano_solicitado = request.args.get(
        "ano_apresentacao",
        request.args.get("ano", obter_ano_apresentacao_padrao()),
    )

    try:
        ano_apresentacao = DatabaseConnection.validar_ano_apresentacao(
            ano_solicitado
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    db = DatabaseConnection(ano_apresentacao=ano_apresentacao)

    if not db.connect():
        return jsonify({"error": "Falha ao conectar no banco de dados da Domínio."}), 500

    try:
        dados = db.get_relatorio_ebef()
        try:
            # A ReceitaWS apenas acrescenta o país de origem do QSA disponível
            # no cache local. Ela não altera a classificação jurídica do e-BEF.
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
        agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
        return jsonify(
            {
                "dados": dados,
                "meta": {
                    "total": len(dados),
                    "ano_apresentacao": db.ano_apresentacao,
                    "ano_referencia": db.ano_referencia,
                    "gerado_em": agora.isoformat(),
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


if __name__ == "__main__":
    debug_ativo = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug_ativo, port=5000)
