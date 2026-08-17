import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, render_template

from database.db_conection import DatabaseConnection


app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/ebef")
def api_ebef():
    db = DatabaseConnection()

    if not db.connect():
        return jsonify({"error": "Falha ao conectar no banco de dados da Domínio."}), 500

    try:
        dados = db.get_relatorio_ebef()
        agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
        return jsonify(
            {
                "dados": dados,
                "meta": {
                    "total": len(dados),
                    "ano_referencia": db.ano_referencia,
                    "gerado_em": agora.isoformat(),
                    "classificacao_preliminar": True,
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
