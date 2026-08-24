from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


ROOT_DIR = Path(__file__).resolve().parents[1]


def load_module(module_name: str, relative_path: str, *, env: dict[str, str], boto3_clients: dict[str, Any], dynamodb_resource: Any):
    """Carrega um módulo do projeto com boto3 e variáveis de ambiente fakeados."""
    module_path = ROOT_DIR / relative_path

    def fake_client(service_name: str, region_name: str | None = None):
        return boto3_clients.get(service_name, MagicMock(name=f"{service_name}_client"))

    with patch.dict(os.environ, env, clear=True), patch("boto3.client", side_effect=fake_client), patch("boto3.resource", return_value=dynamodb_resource):
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Não foi possível carregar {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module


@dataclass
class FakeResponse:
    status_code: int = 200
    text: str = "OK"
    body_text: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class FakeBody:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class FakeTable:
    def __init__(self):
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.put_calls: list[dict[str, Any]] = []
        self.update_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.scan_calls: list[dict[str, Any]] = []

    def put_item(self, Item):
        self.put_calls.append({"Item": Item})
        self.items[(Item["pk"], Item["sk"])] = dict(Item)
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def get_item(self, Key):
        self.get_calls.append({"Key": Key})
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues):
        self.update_calls.append(
            {
                "Key": Key,
                "UpdateExpression": UpdateExpression,
                "ExpressionAttributeValues": ExpressionAttributeValues,
            }
        )
        item = self.items.setdefault((Key["pk"], Key["sk"]), {"pk": Key["pk"], "sk": Key["sk"]})
        if ":f" in ExpressionAttributeValues:
            item["ativo"] = ExpressionAttributeValues[":f"]
        if ":ts" in ExpressionAttributeValues:
            item["removido_em"] = ExpressionAttributeValues[":ts"]
        return {"ResponseMetadata": {"HTTPStatusCode": 200}}

    def scan(self, FilterExpression=None, Select=None, ExclusiveStartKey=None):
        self.scan_calls.append(
            {
                "FilterExpression": FilterExpression,
                "Select": Select,
                "ExclusiveStartKey": ExclusiveStartKey,
            }
        )
        items = [item for item in self.items.values() if item.get("sk") == "INFO" and item.get("ativo")]
        if Select == "COUNT":
            return {"Count": len(items)}
        return {"Items": [dict(item) for item in items]}


class FakeDynamoResource:
    def __init__(self):
        self.tables: dict[str, FakeTable] = {}

    def Table(self, name: str):
        return self.tables.setdefault(name, FakeTable())


class FakeSsmClient:
    def __init__(self, parameters: dict[str, str]):
        self.parameters = parameters
        self.calls: list[dict[str, Any]] = []

    def get_parameter(self, Name, WithDecryption=True):
        self.calls.append({"Name": Name, "WithDecryption": WithDecryption})
        return {"Parameter": {"Value": self.parameters[Name]}}


class FakeLambdaClient:
    def __init__(self):
        self.calls: list[dict[str, Any]] = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        return {"StatusCode": 202}


class FakeBedrockClient:
    def __init__(self, text: str = "Mensagem teste gerada pela IA"):
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def invoke_model(self, **kwargs):
        self.calls.append(kwargs)
        return {"body": FakeBody({"content": [{"text": self.text}]})}


def default_env() -> dict[str, str]:
    return {
        "AWS_REGION": "sa-east-1",
        "DYNAMO_TABLE": "motivafit-dados",
        "PARAM_META_TOKEN": "/motivafit/meta/token",
        "PARAM_META_PHONE_ID": "/motivafit/meta/phone_id",
        "PARAM_META_APP_SECRET": "/motivafit/meta/app_secret",
        "META_VERIFY_TOKEN": "verify-token",
        "ADMIN_NUMERO": "+5511999887766",
        "SENDER_LAMBDA_NAME": "MotivaFit-sender",
        "TEMPLATE_NAME": "fitbot_mensagem_diaria",
        "TEMPLATE_LANGUAGE": "pt_BR",
    }
