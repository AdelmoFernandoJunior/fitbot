from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import MagicMock

from tests.helpers import FakeDynamoResource, FakeLambdaClient, FakeSsmClient, default_env, load_module


class FitbotCommandsTests(unittest.TestCase):
    def setUp(self):
        self.dynamo = FakeDynamoResource()
        self.ssm = FakeSsmClient(
            {
                "/motivafit/meta/token": "token-123",
                "/motivafit/meta/phone_id": "phone-123",
            }
        )
        self.lambda_client = FakeLambdaClient()
        self.module = load_module(
            "fitbot_commands_handler_test",
            "lambdas/fitbot_commands/handler.py",
            env=default_env(),
            boto3_clients={"ssm": self.ssm, "lambda": self.lambda_client},
            dynamodb_resource=self.dynamo,
        )

    def test_formatar_numero_normaliza_para_e164(self):
        self.assertEqual(self.module.formatar_numero("+55 11-99988-7766"), "+5511999887766")

    def test_extrair_mensagem_decodifica_body_base64(self):
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"from": "5511999887766", "type": "text", "text": {"body": "!ajuda"}}
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        event = {"body": base64.b64encode(json.dumps(payload).encode()).decode(), "isBase64Encoded": True}

        mensagem = self.module.extrair_mensagem(event)

        self.assertEqual(mensagem, {"from": "5511999887766", "text": "!ajuda"})

    def test_handler_get_verifica_webhook(self):
        event = {
            "httpMethod": "GET",
            "queryStringParameters": {
                "hub.mode": "subscribe",
                "hub.verify_token": "verify-token",
                "hub.challenge": "12345",
            },
        }

        response = self.module.handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["Content-Type"], "text/plain")
        self.assertEqual(response["body"], "12345")

    def test_handler_post_adicionar_numero_persiste_e_responde(self):
        post_calls = []

        def fake_post(url, json=None, headers=None, timeout=None):
            post_calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return MagicMock(ok=True, status_code=200, text="ok")

        self.module.requests.post = fake_post

        event = {
            "httpMethod": "POST",
            "body": json.dumps(
                {
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "messages": [
                                            {"from": "5511999887766", "type": "text", "text": {"body": "!adicionar +5511888777666"}}
                                        ]
                                    }
                                }
                            ]
                        }
                    ]
                }
            ),
            "isBase64Encoded": False,
        }

        response = self.module.handler(event, None)

        table = self.dynamo.Table("motivafit-dados")
        self.assertIn(("NUMERO#+5511888777666", "INFO"), table.items)
        self.assertEqual(response["statusCode"], 200)
        self.assertIn("adicionado", json.loads(response["body"])["message"])
        self.assertEqual(len(post_calls), 1)

    def test_handler_admin_bloqueia_e_responde_erro(self):
        self.module.requests.post = lambda *args, **kwargs: MagicMock(ok=True, status_code=200, text="ok")

        event = {
            "httpMethod": "POST",
            "body": json.dumps(
                {
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "messages": [
                                            {"from": "5511888777666", "type": "text", "text": {"body": "!lista"}}
                                        ]
                                    }
                                }
                            ]
                        }
                    ]
                }
            ),
            "isBase64Encoded": False,
        }

        response = self.module.handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(len(self.lambda_client.calls), 0)
        self.assertEqual(len(self.ssm.calls), 2)
        self.assertEqual(self.ssm.calls[0]["Name"], "/motivafit/meta/token")

    def test_handler_enviar_agora_invoca_sender_async(self):
        self.module.ADMIN_NUMERO = ""
        self.module.requests.post = lambda *args, **kwargs: MagicMock(ok=True, status_code=200, text="ok")

        event = {
            "httpMethod": "POST",
            "body": json.dumps(
                {
                    "entry": [
                        {
                            "changes": [
                                {
                                    "value": {
                                        "messages": [
                                            {"from": "5511999887766", "type": "text", "text": {"body": "!enviar agora"}}
                                        ]
                                    }
                                }
                            ]
                        }
                    ]
                }
            ),
            "isBase64Encoded": False,
        }

        response = self.module.handler(event, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(len(self.lambda_client.calls), 1)
        self.assertEqual(self.lambda_client.calls[0]["FunctionName"], "MotivaFit-sender")


if __name__ == "__main__":
    unittest.main()
