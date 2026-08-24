from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from tests.helpers import FakeBedrockClient, FakeDynamoResource, FakeSsmClient, default_env, load_module


class FitbotSenderTests(unittest.TestCase):
    def setUp(self):
        self.dynamo = FakeDynamoResource()
        table = self.dynamo.Table("motivafit-dados")
        table.put_item(
            Item={
                "pk": "NUMERO#+5511999887766",
                "sk": "INFO",
                "numero": "+5511999887766",
                "ativo": True,
            }
        )
        self.ssm = FakeSsmClient(
            {
                "/motivafit/meta/token": "token-123",
                "/motivafit/meta/phone_id": "phone-123",
            }
        )
        self.bedrock = FakeBedrockClient(text="Mensagem IA de teste")
        self.module = load_module(
            "fitbot_sender_handler_test",
            "lambdas/fitbot_sender/handler.py",
            env=default_env(),
            boto3_clients={"bedrock-runtime": self.bedrock, "ssm": self.ssm},
            dynamodb_resource=self.dynamo,
        )

    def test_gerar_mensagem_consume_bedrock(self):
        texto = self.module.gerar_mensagem("sono e recuperação")

        self.assertEqual(texto, "Mensagem IA de teste")
        self.assertEqual(len(self.bedrock.calls), 1)
        self.assertEqual(self.bedrock.calls[0]["modelId"], "anthropic.claude-3-haiku-20240307-v1:0")

    def test_enviar_whatsapp_monta_payload_de_template(self):
        post_calls = []

        def fake_post(url, json=None, headers=None, timeout=None):
            post_calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return MagicMock(status_code=200, ok=True, text="ok")

        self.module.requests.post = fake_post

        sucesso = self.module.enviar_whatsapp("+5511999887766", "Mensagem IA de teste", "token-123", "phone-123")

        self.assertTrue(sucesso)
        self.assertEqual(post_calls[0]["url"], "https://graph.facebook.com/v19.0/phone-123/messages")
        self.assertEqual(post_calls[0]["json"]["template"]["name"], "fitbot_mensagem_diaria")
        self.assertEqual(post_calls[0]["json"]["template"]["components"][0]["parameters"][0]["text"], "Mensagem IA de teste")

    def test_handler_envia_para_destinatarios_e_grava_historico(self):
        post_calls = []

        def fake_post(url, json=None, headers=None, timeout=None):
            post_calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            return MagicMock(status_code=200, ok=True, text="ok")

        self.module.requests.post = fake_post

        response = self.module.handler({}, None)

        self.assertEqual(response["statusCode"], 200)
        payload = json.loads(response["body"])
        self.assertEqual(payload["enviados"], 1)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(self.bedrock.calls[0]["modelId"], "anthropic.claude-3-haiku-20240307-v1:0")
        self.assertEqual(self.ssm.calls[0]["Name"], "/motivafit/meta/token")
        self.assertEqual(len(post_calls), 1)
        history_table = self.dynamo.Table("motivafit-dados")
        self.assertTrue(any(key[0].startswith("HISTORICO#") and key[1].startswith("ENVIO#") for key in history_table.items))

    def test_registrar_historico_nao_sobrescreve_execucoes(self):
        self.module.registrar_historico("Mensagem 1", 1, 1)
        self.module.registrar_historico("Mensagem 2", 1, 1)

        history_table = self.dynamo.Table("motivafit-dados")
        historicos = [key for key in history_table.items if key[0].startswith("HISTORICO#")]
        self.assertEqual(len(historicos), 2)

    def test_handler_sem_destinatarios_retorna_sem_enviar(self):
        empty_dynamo = FakeDynamoResource()
        empty_module = load_module(
            "fitbot_sender_handler_empty_test",
            "lambdas/fitbot_sender/handler.py",
            env=default_env(),
            boto3_clients={"bedrock-runtime": FakeBedrockClient(text="Mensagem IA de teste"), "ssm": self.ssm},
            dynamodb_resource=empty_dynamo,
        )
        empty_module.requests.post = lambda *args, **kwargs: MagicMock(status_code=200, ok=True, text="ok")

        response = empty_module.handler({}, None)

        self.assertEqual(response["statusCode"], 200)
        self.assertIn("Nenhum destinatário cadastrado", response["body"])


if __name__ == "__main__":
    unittest.main()
