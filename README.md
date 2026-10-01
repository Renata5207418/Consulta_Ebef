# 📊 Auditor e-BEF — Auditoria e Comunicação de Beneficiários Finais

![Demonstração do Painel Auditor e-BEF](static/tabela_consulta.gif)

Sistema desenvolvido em Python e Flask para analisar, auditar e classificar a carteira de clientes de escritórios contábeis quanto à obrigatoriedade de entrega do **e-BEF — Formulário Digital de Beneficiários Finais**, além de permitir a comunicação individual ou em lote com as empresas enquadradas.

O projeto foi desenvolvido inicialmente para integração com o **Domínio Sistemas / Thomson Reuters**, utilizando banco **Sybase SQL Anywhere**.

---

## 🎯 O que o projeto faz?

A partir das informações existentes no sistema contábil, o Auditor e-BEF:

- identifica as matrizes ativas;
- consolida informações de matriz e filiais;
- analisa natureza jurídica;
- valida CNPJs e CPFs;
- analisa o Quadro de Sócios e Administradores (QSA);
- identifica presença de sócios pessoa jurídica;
- trata Sociedades em Conta de Participação (SCP);
- analisa critérios relacionados ao faturamento;
- classifica cada empresa conforme sua situação perante o e-BEF;
- destaca empresas que precisam de revisão manual;
- permite incluir excepcionalmente empresas na comunicação;
- consulta o e-mail cadastrado diretamente no Domínio;
- envia o comunicado do e-BEF individualmente ou em lote;
- mantém histórico dos envios realizados.

O objetivo é reduzir significativamente o trabalho manual de triagem da carteira.

---

# 🔎 Auditoria e-BEF

## Classificação das empresas

O sistema aplica as regras configuradas para o e-BEF e classifica cada empresa de acordo com sua situação.

Entre os principais resultados estão:

- 🟢 **DISPENSADA**  
  Empresa enquadrada em hipótese de dispensa.

- 🔴 **OBRIGADA**  
  Empresa enquadrada na obrigatoriedade do e-BEF.

- 🟡 **FASEAMENTO**  
  Empresa alcançada pelas regras de entrada gradual da obrigação.

- 🟠 **DISPENSA PROVÁVEL**  
  Empresa cujo enquadramento depende de validações complementares, como faturamento.

- ⚠️ **DADOS INCONSISTENTES**  
  Cadastro com CNPJ, CPF ou outras informações que precisam de correção.

- 🔎 **REVISÃO MANUAL**  
  Situação em que a análise automática não é suficiente e exige avaliação humana.

A classificação apresentada pelo sistema serve como apoio à auditoria da carteira e permite concentrar a análise manual apenas nas situações que realmente exigem intervenção.

---

# ⚙️ Como funciona a auditoria?

## 1. Consolidação de matriz e filiais

As empresas são agrupadas pela raiz do CNPJ, considerando que a análise e a comunicação são centralizadas na matriz.

---

## 2. Validação documental

O sistema verifica a consistência dos documentos cadastrados, incluindo:

- CNPJ;
- CPF;
- estrutura cadastral necessária para a análise.

Cadastros inconsistentes são destacados para correção.

---

## 3. Análise do QSA

O quadro societário é analisado para identificar, entre outros pontos:

- sócios pessoas físicas;
- sócios pessoas jurídicas;
- composição societária;
- situações que alteram o enquadramento da empresa.

---

## 4. Tratamento de SCP

Sociedades em Conta de Participação são identificadas e tratadas de acordo com sua estrutura, permitindo consolidar informações dos sócios participantes e do sócio ostensivo.

---

## 5. Análise de faturamento

Quando necessário, o sistema utiliza informações de faturamento para auxiliar na aplicação das regras de faseamento da obrigação.

---

## 6. Revisão manual

Casos que não podem ser definidos com segurança exclusivamente pelas regras automáticas são apresentados separadamente para revisão.

Isso evita que uma situação subjetiva seja automaticamente tratada como obrigada ou dispensada.

---

# ✉️ Comunicação e-BEF

Além da auditoria, o sistema possui uma tela específica para comunicação com os clientes.

A tela **Comunicação e-BEF** apresenta as empresas selecionadas para comunicação e utiliza como endereço oficial o e-mail cadastrado na matriz no **Domínio Sistemas**.

São exibidos:

- código da empresa;
- razão social;
- CNPJ;
- e-mail cadastrado no Domínio;
- situação do e-mail;
- origem da inclusão;
- situação do envio;
- ações disponíveis.

---

## 📧 Validação de e-mails

Os e-mails são obtidos diretamente do cadastro da empresa no Domínio.

O sistema diferencia:

- **Formato válido**
- **Sem e-mail**
- **Formato inválido**

Empresas sem endereço válido não podem ser selecionadas para envio.

A correção do e-mail deve ser realizada diretamente no cadastro do **Domínio Sistemas**, mantendo o ERP como fonte oficial da informação.

---

# ➕ Inclusão manual na Comunicação

Nem toda empresa que precisa receber o comunicado necessariamente será classificada automaticamente como obrigada.

Para esses casos, a tela de Comunicação possui a opção:

**+ Incluir empresa**

A empresa pode ser localizada por:

- código;
- razão social;
- CNPJ;
- e-mail.

Uma inclusão manual:

- vale somente para o exercício selecionado;
- não altera a classificação da auditoria;
- não altera dados no Domínio;
- pode ser removida posteriormente;
- não apaga eventual histórico de envios.

Na tabela, a coluna **Origem** identifica se a empresa entrou:

- **Automática**
- **Manual**

Quando os dados da Consulta e-BEF já estão carregados no navegador, o sistema reutiliza essas informações para tornar a busca mais rápida e evitar reprocessamentos desnecessários.

---

# 📨 Envio individual

Cada empresa possui uma ação **Enviar**.

Antes do envio é exibida uma prévia contendo:

- destinatário;
- assunto;
- corpo HTML do e-mail;
- anexo.

A prévia é montada pelo mesmo serviço utilizado no envio real, evitando a existência de versões diferentes da mensagem no frontend e no backend.

---

# 📬 Envio em lote

Também é possível selecionar várias empresas e utilizar:

**Enviar selecionados**

Mesmo no envio em lote, **cada empresa recebe uma mensagem individual**.

Exemplo:

```text
Empresa A → e-mail individual para destinatário A
Empresa B → e-mail individual para destinatário B
Empresa C → e-mail individual para destinatário C
```

O sistema não utiliza uma única mensagem com vários destinatários em CC ou BCC.

Cada mensagem é montada separadamente e pode conter suas próprias informações antes de ser enviada pelo SMTP.

---

# 🧪 Modo de teste

Antes de liberar o envio para os clientes, é possível redirecionar todos os e-mails para um endereço de teste.

No `.env`:

```env
EBEF_EMAIL_DESTINO_TESTE=seu-email@empresa.com.br
```

Enquanto essa variável estiver preenchida:

- nenhum e-mail é enviado ao cliente;
- todos os envios são direcionados ao endereço informado;
- cada empresa continua gerando uma mensagem separada;
- o assunto recebe identificação de teste;
- o histórico registra o disparo como teste.

Para ativar o envio real:

```env
EBEF_EMAIL_DESTINO_TESTE=
```

---

# 📎 Comunicado em PDF

O e-mail acompanha o arquivo:

```text
Comunicado - Formulário Digital de Beneficiários Finais.pdf
```

O documento contém as informações detalhadas sobre:

- obrigatoriedade;
- prazos;
- etapas;
- situações de dispensa;
- penalidades;
- utilização da conta gov.br;
- orientações para realização do procedimento.

O corpo do e-mail é propositalmente mais objetivo, enquanto o comunicado anexo concentra as informações detalhadas.

---

# ⚠️ Destaque para penalidades

O comunicado informa que a ausência de entrega, omissões ou informações incorretas podem gerar consequências como:

- suspensão do CNPJ;
- bloqueio de movimentações bancárias;
- multas mensais;
- demais consequências aplicáveis às informações incorretas.

Por esse motivo, o corpo do e-mail dá destaque especial a essa informação e direciona o cliente para leitura do comunicado completo.

---

# 🕓 Histórico de envios

Os envios realizados pela tela de Comunicação são registrados localmente.

O histórico permite identificar:

- empresa;
- exercício;
- CNPJ;
- destinatário;
- assunto;
- anexo;
- data da tentativa;
- situação;
- eventual erro.

Entre os estados utilizados estão:

```text
ENVIADO
TESTE
ERRO
```

Um envio de teste não é considerado como comunicação definitiva ao cliente.

Empresas que já receberam uma comunicação real ficam identificadas na interface e podem ser reenviadas manualmente quando necessário.

---

# 🗃️ Banco local da Comunicação

O histórico e as inclusões manuais são armazenados em SQLite:

```text
data/ebef_comunicacao.sqlite3
```

Esse banco é independente do banco da Domínio.

Nenhuma alteração cadastral é realizada diretamente no banco do ERP.

---

# 🏢 Compatibilidade com Domínio Sistemas

O projeto foi construído para bancos **Sybase SQL Anywhere**, utilizando o layout de tabelas do:

**Thomson Reuters — Domínio Sistemas**

As consultas utilizam tabelas do schema:

```text
bethadba
```

O acesso ao banco da Domínio é utilizado apenas para leitura.

---

## Utiliza outro ERP contábil?

A lógica de classificação em Python pode ser adaptada para outros sistemas contábeis.

Para utilizar, por exemplo:

- Alterdata;
- Questor;
- Fortes;
- SCI;
- outros ERPs;

é necessário adaptar principalmente:

- conexão com o banco;
- consultas SQL;
- origem dos dados cadastrais;
- origem do QSA;
- origem do faturamento.

A regra de classificação pode permanecer separada da camada de acesso ao banco.

---

# 🛠️ Tecnologias utilizadas

- Python
- Flask
- HTML
- JavaScript
- Tailwind CSS
- SQL Anywhere
- ODBC
- SQLite
- SMTP / Microsoft 365
- python-dotenv

---

# 📁 Estrutura principal

```text
ConsultaE_BEF/
│
├── main.py
│
├── database/
│   ├── db_conection.py
│   ├── comunicacao_envios.py
│   └── ...
│
├── services/
│   └── email_service.py
│
├── templates/
│   ├── index.html
│   └── comunicacao.html
│
├── static/
│   └── ...
│
├── resources/
│   └── comunicado_ebef.pdf
│
├── data/
│   └── ebef_comunicacao.sqlite3
│
├── .env
├── .env.example
└── README.md
```

---

# 🚀 Como começar

## Pré-requisitos

- Python 3.8 ou superior;
- Driver ODBC compatível com SQL Anywhere;
- acesso de leitura ao banco da Domínio;
- conta de e-mail autorizada para envio SMTP;
- acesso à rede onde o banco SQL Anywhere está disponível.

---

# 📦 Instalação

Clone o repositório:

```bash
git clone https://github.com/seu-usuario/auditor-ebef.git
cd auditor-ebef
```

Crie o ambiente virtual:

```bash
python -m venv .venv
```

Ative o ambiente.

### Linux

```bash
source .venv/bin/activate
```

### Windows

```powershell
.venv\Scripts\Activate.ps1
```

Instale as dependências:

```bash
pip install -r requirements.txt
```

---

# 🔐 Configuração

Crie um arquivo:

```text
.env
```

Use o `.env.example` como referência.

Exemplo:

```env
# Domínio Sistemas

DOMINIO_HOST=192.168.0.10
DOMINIO_PORT=2638
DOMINIO_DB=nome_do_banco
DOMINIO_USER=usuario
DOMINIO_PASSWORD=senha
DOMINIO_ENGINE=dominio


# e-BEF

EBEF_CODIGO_MAXIMO=9999
FLASK_DEBUG=true


# SMTP

SMTP_SERVER=smtp.office365.com
SMTP_PORT=587
SMTP_USER=societario@empresa.com.br
SMTP_PASSWORD=senha_do_email
SMTP_TIMEOUT=30

EBEF_EMAIL_ASSUNTO=Comunicado importante | e-BEF - Beneficiários Finais


# Modo de teste

EBEF_EMAIL_DESTINO_TESTE=seu-email@empresa.com.br
```

> Nunca versione o arquivo `.env`.

---

# ▶️ Executando

Com o ambiente virtual ativo:

```bash
python main.py
```

Por padrão, o sistema estará disponível em:

```text
http://127.0.0.1:5000
```

---

# 🖥️ Telas principais

## Consulta e-BEF

Responsável pela auditoria e classificação da carteira.

Permite visualizar rapidamente:

- empresas obrigadas;
- dispensadas;
- empresas em faseamento;
- inconsistências;
- situações para revisão manual.

---

## Comunicação e-BEF

Responsável pela preparação e envio das comunicações.

Permite:

- consultar e-mails cadastrados;
- incluir empresas manualmente;
- selecionar empresas;
- enviar individualmente;
- enviar em lote;
- visualizar a mensagem antes do disparo;
- consultar situação do envio;
- reenviar uma comunicação;
- remover uma inclusão manual.

---

# 🔒 Segurança

O sistema não deve armazenar credenciais diretamente no código-fonte.

Informações sensíveis devem permanecer exclusivamente no `.env`, incluindo:

```text
DOMINIO_PASSWORD
SMTP_PASSWORD
```

O arquivo `.env` deve permanecer no `.gitignore`.

Bancos SQLite de execução e outros dados locais também não devem ser versionados.

---

# ⚠️ Ambiente de produção

O servidor interno do Flask:

```bash
python main.py
```

é adequado para desenvolvimento e uso controlado.

Para disponibilização como serviço em ambiente de produção, recomenda-se executar a aplicação através de um servidor WSGI apropriado.

---

# 📌 Objetivo do projeto

O Auditor e-BEF foi criado para transformar um processo que exigiria análise manual de toda a carteira em um fluxo de trabalho concentrado:

```text
CARTEIRA DE CLIENTES
        ↓
AUDITORIA AUTOMÁTICA
        ↓
CLASSIFICAÇÃO
        ↓
REVISÃO DAS EXCEÇÕES
        ↓
COMUNICAÇÃO
        ↓
ENVIO E HISTÓRICO
```

A automação não elimina a análise profissional nos casos subjetivos.

Ela reduz a quantidade de empresas que precisam ser analisadas manualmente e organiza todo o processo de identificação e comunicação do e-BEF.
```
