from __future__ import annotations
import pytest
from pathlib import Path
import yaml

@pytest.fixture
def sample_spec():
    return {
        "openapi": "3.0.3",
        "info": {"title": "API para pruebas", "version": "1"},
        "servers": [{"url": "https://api.invalid"}],
        "components": {
            "schemas": {
                "User": {"type": "object", "properties": {"name": {"type": "string"}}},
                "Color": {"type": "object", "properties": {"name": {"type": "string"}}},
                "Unused": {"type": "object", "properties": {"id": {"type": "string"}}},
            },
            "securitySchemes": {
                "OAuth": {"type": "oauth2", "flows": {"clientCredentials": {
                    "tokenUrl": "https://ignored.invalid/token", "scopes": {"read": "read"}}}},
                "Basic": {"type": "http", "scheme": "basic"},
            },
        },
        "paths": {
            "/users": {"get": {"tags": ["Users"], "operationId": "getUsers", "security": [{"Basic": []}],
                 "responses": {"200": {"description": "OK", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/User"}}}}}}},
            "/colors": {"get": {"tags": ["Catalogs"], "operationId": "getColors", "security": [{"OAuth": ["read"]}],
                 "responses": {"200": {"description": "OK", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Color"}}}}}}},
        },
    }

@pytest.fixture
def spec_file(tmp_path, sample_spec):
    path = tmp_path / "input.yaml"
    path.write_text(yaml.safe_dump(sample_spec), encoding="utf-8")
    return path
