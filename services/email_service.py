import html
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


class EmailEbefService:
    NOME_ANEXO = "Comunicado - Formulário Digital de Beneficiários Finais.pdf"

    def __init__(self):
        pasta_raiz = Path(__file__).resolve().parent.parent

        self.server = os.getenv("SMTP_SERVER", "").strip()
        self.port = int(os.getenv("SMTP_PORT", "587"))
        self.user = os.getenv("SMTP_USER", "").strip()
        self.password = os.getenv("SMTP_PASSWORD", "")
        self.from_email = self.user
        self.from_name = os.getenv("NOME_ESCRITORIO", "").strip()
        self.timeout = int(os.getenv("SMTP_TIMEOUT", "30"))
        self.assunto = os.getenv(
            "EBEF_EMAIL_ASSUNTO",
            "Comunicado - e-BEF - Formulário Digital de Beneficiários Finais",
        ).strip()
        self.destino_teste = os.getenv("EBEF_EMAIL_DESTINO_TESTE", "").strip()
        self.modo_teste = bool(self.destino_teste)

        caminho_padrao = pasta_raiz / "resources" / "comunicado_ebef.pdf"
        self.caminho_comunicado = Path(
            os.getenv("EBEF_COMUNICADO_PDF", str(caminho_padrao))
        ).expanduser()
        self.nome_anexo = self.NOME_ANEXO
        self.smtp = None

        if not self.caminho_comunicado.is_file():
            raise FileNotFoundError(
                f"Comunicado e-BEF não encontrado em: {self.caminho_comunicado}"
            )

    def _validar_configuracao_smtp(self):
        faltantes = []
        if not self.server:
            faltantes.append("SMTP_SERVER")
        if not self.user:
            faltantes.append("SMTP_USER")
        if not self.password:
            faltantes.append("SMTP_PASSWORD")

        if faltantes:
            raise ValueError(
                "Configuração SMTP incompleta. Preencha: " + ", ".join(faltantes)
            )

    def conectar(self):
        self._validar_configuracao_smtp()

        smtp = smtplib.SMTP(self.server, self.port, timeout=self.timeout)
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(self.user, self.password)
        self.smtp = smtp
        return self

    def fechar(self):
        if not self.smtp:
            return

        try:
            self.smtp.quit()
        except Exception:
            try:
                self.smtp.close()
            except Exception:
                pass
        finally:
            self.smtp = None

    def __enter__(self):
        return self.conectar()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.fechar()

    @staticmethod
    def _formatar_cnpj(cnpj):
        documento = "".join(c for c in str(cnpj or "") if c.isalnum())
        if len(documento) == 14:
            return (
                f"{documento[:2]}.{documento[2:5]}.{documento[5:8]}/"
                f"{documento[8:12]}-{documento[12:]}"
            )
        return str(cnpj or "")

    def _montar_corpo_texto(self, razao_social, cnpj):
        return f"""E-BEF - FORMULÁRIO DIGITAL DE BENEFICIÁRIOS FINAIS

    Prezado(a) cliente,

    A Receita Federal instituiu o Formulário Digital de Beneficiários Finais (e-BEF), nova obrigação acessória destinada à identificação das pessoas físicas que, em última instância, possuem, controlam ou exercem influência significativa sobre as empresas.

    A obrigatoriedade já alcança determinados tipos de empresas em 2026, com prazo para a primeira entrega até 31/12/2026, conforme cada situação.

    ATENÇÃO ÀS PENALIDADES

    A ausência de entrega, omissões ou informações incorretas podem resultar em suspensão do CNPJ, bloqueio de movimentações bancárias e multas mensais entre R$ 500 e R$ 1.500, além de outras consequências previstas para informações incorretas.

    O comunicado completo em PDF, anexo a este e-mail, apresenta os prazos, etapas, situações de dispensa e orientações para realização do procedimento.

    IMPORTANTE

    Cada beneficiário final indicado deverá realizar sua própria etapa de confirmação e assinatura utilizando conta gov.br nível prata ou ouro ou certificado ICP-Brasil.

    Para solicitar o passo a passo ou esclarecer dúvidas, entre em contato pelo e-mail {self.user}.

    Atenciosamente,
    {self.from_name}"""

    def _montar_corpo_html(self, razao_social, cnpj):
        razao = html.escape(str(razao_social or ""))
        cnpj_formatado = html.escape(self._formatar_cnpj(cnpj))

        return f"""
        <html>
        <body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,Helvetica,sans-serif;color:#252525;">
          <div style="max-width:700px;margin:0 auto;background:#fff;padding:30px 36px;">
        
            <div style="border-left:5px solid #f5b400;padding-left:14px;margin-bottom:24px;">
              <h1 style="font-size:20px;margin:0;color:#111;">
                E-BEF - FORMULÁRIO DIGITAL DE BENEFICIÁRIOS FINAIS
              </h1>
            </div>
        
            <p>Prezado(a) cliente,</p>
        
            <p>
              A Receita Federal instituiu o <strong>Formulário Digital de Beneficiários Finais (e-BEF)</strong>,
              nova obrigação acessória destinada à identificação das pessoas físicas que, em última instância,
              possuem, controlam ou exercem influência significativa sobre as empresas.
            </p>
        
            <p>
              A obrigatoriedade já alcança determinados tipos de empresas em <strong>2026</strong>,
              com prazo para a primeira entrega até <strong>31/12/2026</strong>, conforme cada situação.
            </p>
        
            <div style="margin:26px 0;padding:18px 20px;background:#fff3cd;border:1px solid #f5b400;border-left:6px solid #f5b400;">
              <p style="margin:0 0 8px;font-size:17px;font-weight:bold;color:#7a5200;">
                Atenção às penalidades
              </p>
        
              <p style="margin:0;line-height:1.6;">
                A ausência de entrega, omissões ou informações incorretas podem resultar em
                <strong>suspensão do CNPJ</strong>,
                <strong>bloqueio de movimentações bancárias</strong> e
                <strong>multas mensais entre R$ 500 e R$ 1.500</strong>,
                além de outras consequências previstas para informações incorretas.
              </p>
            </div>
        
            <p>
              Preparamos um <strong>comunicado completo em PDF</strong>, anexo a este e-mail,
              com os prazos, etapas, situações de dispensa e orientações para realização do procedimento.
            </p>
        
            <div style="margin:24px 0;padding:16px;background:#f5f5f5;border-left:4px solid #252525;">
              <strong>Importante:</strong>
              cada beneficiário final indicado deverá realizar sua própria etapa de confirmação e assinatura
              utilizando conta gov.br nível prata ou ouro ou certificado ICP-Brasil.
            </div>
        
            <p>
              Para solicitar o passo a passo ou esclarecer dúvidas, entre em contato pelo e-mail
                <strong>{html.escape(self.user)}</strong>.
            </p>
        
            <p style="margin-top:30px;">
              Atenciosamente,<br>
            <strong>{html.escape(self.from_name)}</strong>
            </p>
        
          </div>
        </body>
        </html>
"""

    def montar_mensagem(self, *, destinatario, razao_social, cnpj):
        mensagem = EmailMessage()
        assunto = f"[TESTE] {self.assunto}" if self.modo_teste else self.assunto
        destinatario_real = self.destino_teste if self.modo_teste else destinatario

        mensagem["Subject"] = assunto
        mensagem["From"] = formataddr((self.from_name, self.from_email))
        mensagem["To"] = destinatario_real

        if self.modo_teste:
            mensagem["X-EBEF-Destinatario-Original"] = destinatario

        mensagem.set_content(self._montar_corpo_texto(razao_social, cnpj))
        mensagem.add_alternative(self._montar_corpo_html(razao_social, cnpj), subtype="html")
        mensagem.add_attachment(
            self.caminho_comunicado.read_bytes(),
            maintype="application",
            subtype="pdf",
            filename=self.nome_anexo,
        )
        return mensagem

    def montar_preview(self, *, destinatario, razao_social, cnpj):
        mensagem = self.montar_mensagem(
            destinatario=destinatario,
            razao_social=razao_social,
            cnpj=cnpj,
        )
        parte_html = mensagem.get_body(preferencelist=("html",))
        anexo = next(mensagem.iter_attachments(), None)

        return {
            "assunto": str(mensagem["Subject"] or ""),
            "corpo_html": parte_html.get_content() if parte_html else "",
            "anexo": anexo.get_filename() if anexo else "",
        }

    def enviar(self, *, destinatario, razao_social, cnpj):
        if not self.smtp:
            raise RuntimeError("Conexão SMTP não foi estabelecida.")

        mensagem = self.montar_mensagem(
            destinatario=destinatario,
            razao_social=razao_social,
            cnpj=cnpj,
        )
        self.smtp.send_message(mensagem)
