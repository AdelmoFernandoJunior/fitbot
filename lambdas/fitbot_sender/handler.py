"""
MotivaFit Sender — Lambda disparada pelo EventBridge todo dia às 07:00
Gera mensagem motivacional via Amazon Bedrock (Claude) e envia via Meta WhatsApp API
"""

import json
import logging
import os
import random
from datetime import datetime

import boto3
import requests
from boto3.dynamodb.conditions import Attr

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock  = boto3.client("bedrock-runtime", region_name=os.environ["AWS_REGION"])
dynamodb = boto3.resource("dynamodb",       region_name=os.environ["AWS_REGION"])
ssm      = boto3.client("ssm",             region_name=os.environ["AWS_REGION"])

TABELA_NUMEROS    = os.environ["DYNAMO_TABLE"]
PARAM_META_TOKEN  = os.environ["PARAM_META_TOKEN"]   # SSM: /MotivaFit/meta/token
PARAM_PHONE_ID    = os.environ["PARAM_META_PHONE_ID"] # SSM: /MotivaFit/meta/phone_id
TEMPLATE_NAME     = os.environ["TEMPLATE_NAME"]       # Ex: MotivaFit_mensagem_diaria
TEMPLATE_LANGUAGE = os.environ.get("TEMPLATE_LANGUAGE", "pt_BR")

TEMAS = [
    "hidratação e seus benefícios para o desempenho físico",
    "importância do sono para recuperação muscular",
    "alimentação pré e pós-treino",
    "consistência vs intensidade nos exercícios",
    "mentalidade de atleta e disciplina diária",
    "descanso ativo e recuperação inteligente",
    "proteínas e construção de massa muscular",
    "saúde cardiovascular e exercício aeróbico",
    "mobilidade, flexibilidade e prevenção de lesões",
    "hábitos sustentáveis para vida longa e saudável",
]


def buscar_parametro(nome: str) -> str:
    """Busca valor seguro do SSM Parameter Store."""
    resp = ssm.get_parameter(Name=nome, WithDecryption=True)
    return resp["Parameter"]["Value"]


def gerar_mensagem(tema: str) -> str:
    """Gera mensagem motivacional via Amazon Bedrock (Claude 3 Haiku)."""
    hoje = datetime.now().strftime("%A, %d de %B")

    prompt = f"""Gere uma mensagem motivacional curta (máximo 5 frases) sobre saúde, bem-estar e fitness.

Tema do dia: {tema}
Data: {hoje}

Regras obrigatórias:
- Comece com um emoji relacionado ao tema
- Linguagem direta, positiva e encorajadora
- Inclua 1 dica prática aplicável hoje
- Termine com uma frase de impacto curta
- Use no máximo 3 emojis no total
- Escreva em português do Brasil informal mas respeitoso
- Não use asteriscos, markdown ou formatação especial"""

    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 300,
        "messages": [{"role": "user", "content": prompt}],
    })

    response = bedrock.invoke_model(
        modelId="anthropic.claude-3-haiku-20240307-v1:0",
        body=body,
        contentType="application/json",
        accept="application/json",
    )

    resultado = json.loads(response["body"].read())
    return resultado["content"][0]["text"]


def listar_numeros() -> list[dict]:
    """Retorna todos os destinatários ativos do DynamoDB."""
    tabela = dynamodb.Table(TABELA_NUMEROS)
    resp = tabela.scan(
        FilterExpression=Attr("ativo").eq(True) & Attr("sk").eq("INFO")
    )
    return resp.get("Items", [])


def enviar_whatsapp(numero: str, mensagem: str, token: str, phone_id: str) -> bool:
    """
    Envia mensagem via Meta WhatsApp Business API.
    Usa template aprovado com a mensagem gerada pela IA como variável.
    """
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "template",
        "template": {
            "name": TEMPLATE_NAME,
            "language": {"code": TEMPLATE_LANGUAGE},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": mensagem}
                    ],
                }
            ],
        },
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=10)

    if resp.status_code == 200:
        return True

    logger.error("Erro Meta API para %s: %s — %s", numero, resp.status_code, resp.text)
    return False


def registrar_historico(mensagem: str, enviados: int, total: int):
    """Grava o envio no DynamoDB para histórico."""
    tabela = dynamodb.Table(TABELA_NUMEROS)
    tabela.put_item(Item={
        "pk": f"HISTORICO#{datetime.now().strftime('%Y-%m-%d')}",
        "sk": "ENVIO",
        "mensagem": mensagem,
        "enviados": enviados,
        "total": total,
        "timestamp": datetime.now().isoformat(),
    })


def handler(event, context):
    logger.info("MotivaFit Sender iniciado.")

    # 1. Sortear tema do dia
    tema = random.choice(TEMAS)
    logger.info("Tema: %s", tema)

    # 2. Gerar mensagem via Bedrock
    try:
        mensagem = gerar_mensagem(tema)
        logger.info("Mensagem gerada:\n%s", mensagem)
    except Exception as e:
        logger.error("Erro no Bedrock: %s", str(e))
        raise

    # 3. Buscar credenciais da Meta no SSM
    try:
        meta_token = buscar_parametro(PARAM_META_TOKEN)
        phone_id   = buscar_parametro(PARAM_PHONE_ID)
    except Exception as e:
        logger.error("Erro ao buscar credenciais SSM: %s", str(e))
        raise

    # 4. Listar destinatários
    numeros = listar_numeros()
    logger.info("Destinatários: %d", len(numeros))

    if not numeros:
        logger.warning("Nenhum número cadastrado.")
        return {"statusCode": 200, "body": "Nenhum destinatário cadastrado."}

    # 5. Enviar para cada número
    enviados = 0
    for item in numeros:
        numero = item["numero"]
        sucesso = enviar_whatsapp(numero, mensagem, meta_token, phone_id)
        if sucesso:
            enviados += 1
            logger.info("Enviado para %s", numero)
        else:
            logger.error("Falha ao enviar para %s", numero)

    # 6. Registrar histórico
    registrar_historico(mensagem, enviados, len(numeros))

    logger.info("Resumo: %d/%d enviados.", enviados, len(numeros))
    return {
        "statusCode": 200,
        "body": json.dumps({
            "enviados": enviados,
            "total": len(numeros),
            "tema": tema,
        }),
    }
