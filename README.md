# 🏋️ FitBot AWS — Meta WhatsApp API (100% gratuito)

Bot serverless que gera mensagens motivacionais de saúde e fitness com IA e envia automaticamente para uma lista de contatos no WhatsApp. Custo zero — usa AWS Free Tier + Meta WhatsApp API gratuita.

---

## Por que Meta WhatsApp API?

A Meta oferece **1.000 conversas gratuitas por mês**. Para 100 pessoas recebendo 1 mensagem por dia = 100 conversas/mês. Totalmente dentro do limite gratuito, sem pagar nada.

---

## Serviços utilizados

| Serviço | Função | Custo |
|---|---|---|
| **Lambda** | Executa o bot | Grátis (1M req/mês) |
| **EventBridge** | Agenda o disparo diário | Grátis |
| **DynamoDB** | Armazena números e histórico | Grátis (25 GB) |
| **API Gateway** | Recebe webhook da Meta | Grátis (1M calls/mês) |
| **SSM Parameter Store** | Guarda credenciais com segurança | Grátis |
| **Amazon Bedrock** | Claude 3 Haiku gera a mensagem | ~$0,001/msg (~$3/mês) |
| **Meta WhatsApp API** | Entrega a mensagem no WhatsApp | Grátis (até 1.000/mês) |

**Custo total estimado: ~$3/mês** (só o Bedrock, tudo mais é zero)

---

## Pré-requisitos

- [AWS CLI](https://aws.amazon.com/cli/) configurado com `aws configure`
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- Python 3.12
- Conta Meta for Developers (gratuita)
- Número de WhatsApp Business (chip separado do seu pessoal)
- Amazon Bedrock com acesso ao Claude 3 Haiku habilitado

---

## Estrutura do projeto

```
fitbot-meta/
├── deploy.sh                    # Script de deploy — edite só este
├── README.md
├── lambdas/
│   ├── requirements.txt         # boto3 + requests (sem Twilio)
│   ├── fitbot_sender/
│   │   └── handler.py           # Bedrock → Meta API → envia mensagem
│   └── fitbot_commands/
│       └── handler.py           # Webhook Meta → !adicionar !remover !lista
└── infra/
    └── template.yaml            # SAM — toda infraestrutura AWS
```

---

## Configuração passo a passo

### 1. Criar app no Meta for Developers

1. Acesse [developers.facebook.com](https://developers.facebook.com)
2. Clique em "Meus apps" → "Criar app"
3. Escolha tipo **Business**
4. Adicione o produto **WhatsApp**
5. Anote o **App Secret** (Configurações → Básico)

### 2. Configurar o número WhatsApp Business

1. Dentro do app, vá em **WhatsApp → Configuração da API**
2. Adicione seu número de telefone Business
3. Anote o **Phone Number ID**
4. Gere um **Token de acesso permanente** (Configurações do sistema → Usuários do sistema)

### 3. Criar o template de mensagem

1. Acesse o [Meta Business Manager](https://business.facebook.com)
2. Vá em **Conta do WhatsApp → Modelos de mensagem → Criar modelo**
3. Configure:
   - Nome: `fitbot_mensagem_diaria`
   - Categoria: Marketing ou Utilitário
   - Idioma: Português (BR)
   - Corpo: `{{1}}`  ← a mensagem gerada pela IA vai aqui
4. Envie para aprovação (normalmente aprovado em minutos)

### 4. Configurar o deploy.sh

Edite o arquivo `deploy.sh` e preencha:

```bash
ADMIN_NUMERO="+5511999887766"        # Seu número pessoal (gerencia o bot)
META_VERIFY_TOKEN="sua-string-secreta"
META_TOKEN="EAAxxxxxxxxxx"           # Token de acesso permanente
META_PHONE_ID="123456789"            # Phone Number ID
META_APP_SECRET="xxxxxxxxxx"         # App Secret
```

### 5. Executar o deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

### 6. Configurar o webhook na Meta

Após o deploy, copie a URL exibida e:

1. Vá em **WhatsApp → Configuração → Webhook**
2. Clique em **Editar**
3. Cole a URL do webhook
4. No campo "Token de verificação", coloque o mesmo valor de `META_VERIFY_TOKEN`
5. Clique em **Verificar e salvar**
6. Assine o evento **messages**

---

## Usando os comandos no WhatsApp

Envie mensagens para o número do bot:

| Comando | O que faz |
|---|---|
| `!adicionar +5511999887766` | Adiciona número à lista |
| `!remover +5511999887766` | Remove número da lista |
| `!lista` | Mostra todos os destinatários |
| `!enviar agora` | Dispara a mensagem imediatamente |
| `!ajuda` | Mostra todos os comandos |

---

## Ajustar horário de envio

No `deploy.sh`, altere `HORARIO_UTC` (EventBridge usa UTC, BRT = UTC-3):

```bash
"cron(0 10 * * ? *)"    # 07:00 BRT  (padrão)
"cron(0 11 * * ? *)"    # 08:00 BRT
"cron(30 9 * * ? *)"    # 06:30 BRT
"cron(0 10 * * 2-6 *)"  # 07:00 BRT apenas seg-sex
```

---

## Ver logs

```bash
aws logs tail /aws/lambda/fitbot-sender   --follow
aws logs tail /aws/lambda/fitbot-commands --follow
```

---

## Remover tudo

```bash
aws cloudformation delete-stack --stack-name fitbot-stack --region us-east-1
aws ssm delete-parameter --name /fitbot/meta/token
aws ssm delete-parameter --name /fitbot/meta/phone_id
aws ssm delete-parameter --name /fitbot/meta/app_secret
```
