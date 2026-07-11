"""
MotivaFit Commands — Lambda acionada pelo webhook da Meta WhatsApp API
Processa comandos enviados pelo WhatsApp: !adicionar, !remover, !lista, !enviar agora, !ajuda
"""

import base64
import json
import logging
import os
from datetime import datetime

import boto3
import requests

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"])
ssm = boto3.client("ssm", region_name=os.environ["AWS_REGION"])
lambda_client = boto3.client("lambda", region_name=os.environ["AWS_REGION"])

TABELA_NUMEROS = os.environ["DYNAMO_TABLE"] # DynamoDB para números e histórico
PARAM_META_TOKEN = os.environ["PARAM_META_TOKEN"]  # SSM: /MotivaFit/meta/token
PARAM_META_PHONE_ID = os.environ["PARAM_META_PHONE_ID"] # SSM: /MotivaFit/meta/phone_id
META_VERIFY_TOKEN = os.environ["META_VERIFY_TOKEN"] # Token de verificação do webhook (ex: MotivaFit-webhook-2024)
ADMIN_NUMERO = os.environ.get("ADMIN_NUMERO", "")  # Ex: +5511999887766
SENDER_LAMBDA = os.environ["SENDER_LAMBDA_NAME"]  # Ex: MotivaFit-sender


def buscar_parametro_ssm(nome: str) -> str:
    resp = ssm.get_parameter(Name=nome, WithDecryption=True)
    return resp["Parameter"]["Value"]


def formatar_numero(num: str) -> str:
    return "+" + num.replace("+", "").replace(" ", "").replace("-", "")


def responder_meta(mensagem: str, status_code: int = 200, content_type: str = "application/json") -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": content_type},
        "body": json.dumps({"message": mensagem}),
    }


def verificar_webhook(event) -> dict:
    query = event.get("queryStringParameters") or {}
    mode = query.get("hub.mode")
    token = query.get("hub.verify_token")
    challenge = query.get("hub.challenge")

    if mode == "subscribe" and token == META_VERIFY_TOKEN:
        return {"statusCode": 200, "headers": {"Content-Type": "text/plain"}, "body": challenge or ""}

    return {"statusCode": 403, "headers": {"Content-Type": "text/plain"}, "body": "Forbidden"}


def extrair_mensagem(event) -> dict | None:
    body_raw = event.get("body", "")
    if event.get("isBase64Encoded"):
        body_raw = base64.b64decode(body_raw).decode("utf-8")

    if isinstance(body_raw, str):
        try:
            payload = json.loads(body_raw)
        except ValueError:
            return None
    else:
        payload = body_raw

    entries = payload.get("entry", [])
    if not entries:
        return None

    changes = entries[0].get("changes", [])
    if not changes:
        return None

    value = changes[0].get("value", {})
    messages = value.get("messages", [])
    if not messages:
        return None

    message = messages[0]
    return {
        "from": message.get("from"),
        "text": message.get("text", {}).get("body", "") if message.get("type") == "text" else "",
    }


def enviar_meta_mensagem(numero: str, mensagem: str, token: str, phone_id: str) -> bool:
    url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": numero,
        "type": "text",
        "text": {"body": mensagem},
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    if resp.ok:
        return True

    logger.error("Erro Meta API para %s: %s — %s", numero, resp.status_code, resp.text)
    return False


def adicionar_numero(numero: str) -> tuple[bool, str]:
    """Adiciona número ao DynamoDB. Retorna (sucesso, mensagem)."""
    limpo = "+" + numero.replace("+", "").replace(" ", "").replace("-", "")
    if len(limpo) < 12:
        return False, f"Número inválido: {numero}\nUse formato: +5511999887766"

    tabela = dynamodb.Table(TABELA_NUMEROS)
    existente = tabela.get_item(Key={"pk": f"NUMERO#{limpo}", "sk": "INFO"})

    if "Item" in existente and existente["Item"].get("ativo"):
        return False, f"Número {limpo} já está na lista."

    tabela.put_item(
        Item={
            "pk": f"NUMERO#{limpo}",
            "sk": "INFO",
            "numero": limpo,
            "ativo": True,
            "criado_em": datetime.now().isoformat(),
        }
    )

    total = contar_numeros()
    return True, f"Número {limpo} adicionado!\nTotal na lista: {total} número(s)."


def remover_numero(numero: str) -> tuple[bool, str]:
    """Remove número do DynamoDB (soft delete)."""
    limpo = "+" + numero.replace("+", "").replace(" ", "").replace("-", "")
    tabela = dynamodb.Table(TABELA_NUMEROS)
    existente = tabela.get_item(Key={"pk": f"NUMERO#{limpo}", "sk": "INFO"})

    if "Item" not in existente or not existente["Item"].get("ativo"):
        return False, f"Número {limpo} não encontrado na lista."

    tabela.update_item(
        Key={"pk": f"NUMERO#{limpo}", "sk": "INFO"},
        UpdateExpression="SET ativo = :f, removido_em = :ts",
        ExpressionAttributeValues={
            ":f": False,
            ":ts": datetime.now().isoformat(),
        },
    )
    total = contar_numeros()
    return True, f"Número {limpo} removido.\nTotal na lista: {total} número(s)."


def sair_lista(numero: str) -> tuple[bool, str]:
    """Remove o número do remetente da lista (parar de receber mensagens)."""
    limpo = "+" + numero.replace("+", "").replace(" ", "").replace("-", "")
    tabela = dynamodb.Table(TABELA_NUMEROS)
    existente = tabela.get_item(Key={"pk": f"NUMERO#{limpo}", "sk": "INFO"})

    if "Item" not in existente or not existente["Item"].get("ativo"):
        return False, "Você não está cadastrado na lista."

    tabela.update_item(
        Key={"pk": f"NUMERO#{limpo}", "sk": "INFO"},
        UpdateExpression="SET ativo = :f, removido_em = :ts",
        ExpressionAttributeValues={
            ":f": False,
            ":ts": datetime.now().isoformat(),
        },
    )
    return True, "Você foi removido da lista. Não receberá mais mensagens motivacionais.\n\nDeseja voltar? Envie: !adicionar {limpo}"


def listar_numeros_texto() -> str:
    """Retorna string formatada com todos os números ativos."""
    tabela = dynamodb.Table(TABELA_NUMEROS)
    resp = tabela.scan(
        FilterExpression=boto3.dynamodb.conditions.Attr("ativo").eq(True)
        & boto3.dynamodb.conditions.Attr("sk").eq("INFO")
    )
    items = resp.get("Items", [])

    if not items:
        return "Nenhum número cadastrado.\nUse: !adicionar +5511999887766"

    linhas = [f"{i+1}. {item['numero']}" for i, item in enumerate(items)]
    return f"Destinatários ({len(items)}):\n\n" + "\n".join(linhas)


def contar_numeros() -> int:
    tabela = dynamodb.Table(TABELA_NUMEROS)
    resp = tabela.scan(
        FilterExpression=boto3.dynamodb.conditions.Attr("ativo").eq(True)
        & boto3.dynamodb.conditions.Attr("sk").eq("INFO"),
        Select="COUNT",
    )
    return resp.get("Count", 0)


def disparar_envio_manual() -> str:
    """Invoca a Lambda sender de forma assíncrona."""
    lambda_client.invoke(
        FunctionName=SENDER_LAMBDA,
        InvocationType="Event",  # assíncrono
        Payload=json.dumps({"origem": "manual_whatsapp"}),
    )
    return "Mensagem sendo gerada e enviada agora!\nAguarde alguns segundos."


MENU_AJUDA = """MotivaFit — Comandos disponíveis:

!adicionar +5511999887766
  Adiciona número à lista

!remover +5511999887766
  Remove número da lista

!lista
  Mostra todos os destinatários

!enviar agora
  Dispara mensagem imediatamente

!ajuda
  Mostra este menu

PARAR DE RECEBER MENSAGENS:
  Envie: sair
  Ou: não quero receber mensagens

Números no formato internacional: +55 DDD número"""


def handler(event, context):
    logger.info("MotivaFit Commands acionado.")

    method = event.get("httpMethod", "POST").upper()
    if method == "GET":
        return verificar_webhook(event)

    mensagem_evento = extrair_mensagem(event)
    if not mensagem_evento:
        logger.warning("Webhook Meta recebido sem mensagem válida.")
        return responder_meta("Evento recebido.")

    remetente = formatar_numero(mensagem_evento["from"])
    texto = mensagem_evento["text"].strip()

    logger.info("Mensagem de %s: %s", remetente, texto)

    if ADMIN_NUMERO:
        admin_limpo = formatar_numero(ADMIN_NUMERO)
        if remetente != admin_limpo:
            logger.warning("Acesso negado para %s", remetente)
            meta_token = buscar_parametro_ssm(PARAM_META_TOKEN)
            phone_id = buscar_parametro_ssm(PARAM_META_PHONE_ID)
            enviar_meta_mensagem(remetente, "Acesso não autorizado.", meta_token, phone_id)
            return responder_meta("Acesso não autorizado.")

    if not texto:
        return responder_meta("Mensagem vazia ou tipo não suportado.")

    # Processa comandos e mensagens de parada
    texto_lower = texto.lower().strip()

    if texto_lower in ("sair", "não quero receber mensagens", "nao quero receber mensagens"):
        ok, msg = sair_lista(remetente)
    elif texto_lower.startswith("!adicionar "):
        numero = texto[11:].strip()
        ok, msg = adicionar_numero(numero)
    elif texto_lower.startswith("!remover "):
        numero = texto[9:].strip()
        ok, msg = remover_numero(numero)
    elif texto.lower() == "!lista":
        ok = True
        msg = listar_numeros_texto()
    elif texto.lower() == "!enviar agora":
        ok = True
        msg = disparar_envio_manual()
    elif texto.lower() == "!ajuda":
        ok = True
        msg = MENU_AJUDA
    else:
        ok = False
        msg = "Comando não reconhecido.\nEnvie !ajuda para ver os comandos disponíveis."

    meta_token = buscar_parametro_ssm(PARAM_META_TOKEN)
    phone_id = buscar_parametro_ssm(PARAM_META_PHONE_ID)
    enviado = enviar_meta_mensagem(remetente, msg, meta_token, phone_id)
    if not enviado:
        logger.error("Falha ao enviar resposta para %s", remetente)

    return responder_meta(msg)
