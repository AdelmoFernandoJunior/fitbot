#!/bin/bash
# deploy.sh — Deploy do FitBot com Meta WhatsApp API (100% gratuito)
# Requisitos: AWS CLI, AWS SAM CLI, Python 3.12

set -e

echo "========================================"
echo "  FitBot — Deploy com Meta WhatsApp API"
echo "========================================"

# ─── Configure estes valores antes de executar ───────────────────────────────

AWS_REGION="sa-east-1"
STACK_NAME="fitbot-stack"

# Número admin (quem pode usar os comandos !adicionar, !remover etc.)
# Formato: +5511999887766
ADMIN_NUMERO="+5511999887766"

# Horário de envio (UTC — BRT = UTC-3)
# 10:00 UTC = 07:00 BRT
HORARIO_UTC="cron(0 10 * * ? *)"

# Token de verificação do webhook Meta (crie qualquer string secreta)
# Ex: fitbot-webhook-2024
META_VERIFY_TOKEN="fitbot-webhook-2024"

# Nome do template aprovado no Meta Business Manager
TEMPLATE_NAME="fitbot_mensagem_diaria"

# ─── Credenciais da Meta WhatsApp API ────────────────────────────────────────
# Obtidas em: https://developers.facebook.com → seu app → WhatsApp → API Setup

META_TOKEN="EAAxxxxxxxxxxxxxxxxx"       # Token de acesso permanente
META_PHONE_ID="1234567890"             # Phone Number ID
META_APP_SECRET="xxxxxxxxxxxxxxxx"     # App Secret (Configurações do app)

# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo "1/5 — Salvando credenciais no SSM Parameter Store..."

aws ssm put-parameter \
    --name "/fitbot/meta/token" \
    --value "$META_TOKEN" \
    --type "SecureString" \
    --overwrite \
    --region "$AWS_REGION"

aws ssm put-parameter \
    --name "/fitbot/meta/phone_id" \
    --value "$META_PHONE_ID" \
    --type "SecureString" \
    --overwrite \
    --region "$AWS_REGION"

aws ssm put-parameter \
    --name "/fitbot/meta/app_secret" \
    --value "$META_APP_SECRET" \
    --type "SecureString" \
    --overwrite \
    --region "$AWS_REGION"

echo "   Credenciais salvas com segurança."

echo ""
echo "2/5 — Instalando dependências Python..."

pip install -r lambdas/requirements.txt \
    -t lambdas/fitbot_sender/vendor --quiet

pip install -r lambdas/requirements.txt \
    -t lambdas/fitbot_commands/vendor --quiet

# Garante que o vendor seja carregado no início de cada Lambda
for dir in fitbot_sender fitbot_commands; do
    cat > "lambdas/$dir/__init__.py" << 'PYEOF'
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'vendor'))
PYEOF
done

echo ""
echo "3/5 — Construindo o pacote SAM..."

sam build \
    --template infra/template.yaml \
    --build-dir .aws-sam/build \
    --region "$AWS_REGION"

echo ""
echo "4/5 — Fazendo deploy na AWS..."

sam deploy \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
        AdminNumero="$ADMIN_NUMERO" \
        HorarioCron="$HORARIO_UTC" \
        MetaVerifyToken="$META_VERIFY_TOKEN" \
        TemplateName="$TEMPLATE_NAME" \
    --resolve-s3 \
    --no-confirm-changeset

echo ""
echo "5/5 — Obtendo URL do webhook..."

WEBHOOK_URL=$(aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$AWS_REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='WebhookUrl'].OutputValue" \
    --output text)

echo ""
echo "========================================"
echo "  Deploy concluído!"
echo "========================================"
echo ""
echo "  URL do Webhook:"
echo "  $WEBHOOK_URL"
echo ""
echo "  Próximos passos:"
echo ""
echo "  1. Acesse developers.facebook.com → seu app → WhatsApp → Configuration"
echo "  2. Em 'Webhook', cole a URL acima"
echo "  3. Em 'Verify token', coloque: $META_VERIFY_TOKEN"
echo "  4. Clique em 'Verify and Save'"
echo "  5. Assine o evento: messages"
echo ""
echo "  Depois crie o template de mensagem:"
echo "  Meta Business Manager → Conta do WhatsApp → Modelos de mensagem"
echo "  Nome: $TEMPLATE_NAME"
echo "  Corpo: {{1}}"
echo "========================================"
