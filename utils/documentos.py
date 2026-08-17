import re


def normalizar_documento(valor) -> str:
    """Remove máscara, espaços e outros caracteres do CPF/CNPJ."""
    if valor is None:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(valor).upper())


def validar_cpf(valor) -> bool:
    cpf = re.sub(r"\D", "", str(valor or ""))

    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False

    for tamanho in (9, 10):
        soma = sum(
            int(cpf[indice]) * (tamanho + 1 - indice)
            for indice in range(tamanho)
        )

        digito = (soma * 10) % 11

        if digito == 10:
            digito = 0

        if digito != int(cpf[tamanho]):
            return False

    return True


def validar_cnpj_numerico(valor) -> bool:
    cnpj = re.sub(r"\D", "", str(valor or ""))

    if len(cnpj) != 14 or cnpj == cnpj[0] * 14:
        return False

    pesos_primeiro = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    pesos_segundo = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)

    def calcular_digito(base: str, pesos: tuple) -> str:
        soma = sum(
            int(numero) * peso
            for numero, peso in zip(base, pesos)
        )

        resto = soma % 11
        return "0" if resto < 2 else str(11 - resto)

    primeiro = calcular_digito(cnpj[:12], pesos_primeiro)
    segundo = calcular_digito(
        cnpj[:12] + primeiro,
        pesos_segundo,
    )

    return cnpj[-2:] == primeiro + segundo


def analisar_documento_socio(valor) -> dict:
    documento = normalizar_documento(valor)

    if len(documento) == 11 and documento.isdigit():
        valido = validar_cpf(documento)

        return {
            "tipo": "PF",
            "documento": documento,
            "valido": valido,
            "observacao": "CPF válido" if valido else "CPF inválido",
        }

    if len(documento) == 14 and documento.isdigit():
        valido = validar_cnpj_numerico(documento)

        return {
            "tipo": "PJ",
            "documento": documento,
            "valido": valido,
            "observacao": "CNPJ válido" if valido else "CNPJ inválido",
        }

    # Mantém compatibilidade visual com o CNPJ alfanumérico.
    if len(documento) == 14 and documento.isalnum():
        return {
            "tipo": "PJ",
            "documento": documento,
            "valido": None,
            "observacao": "CNPJ alfanumérico: validação pendente",
        }

    return {
        "tipo": "NAO_IDENTIFICADO",
        "documento": documento,
        "valido": False,
        "observacao": "Documento ausente ou com formato não reconhecido",
    }


def transformar_lista_socios(lista_string) -> list:
    if not lista_string:
        return []

    socios = []
    chaves_adicionadas = set()

    for item in str(lista_string).split(" | "):
        item = item.strip()

        correspondencia = re.match(
            r"^(.*?)\s*\(([^()]*)\)\s*$",
            item,
        )

        if correspondencia:
            nome = correspondencia.group(1).strip()
            inscricao = correspondencia.group(2).strip()
        else:
            nome = item
            inscricao = ""

        analise = analisar_documento_socio(inscricao)
        chave = (
            normalizar_documento(inscricao),
            nome.upper(),
        )

        if chave not in chaves_adicionadas:
            socios.append(
                {
                    "nome": nome,
                    "inscricao_original": inscricao,
                    **analise,
                }
            )
            chaves_adicionadas.add(chave)

    return socios
