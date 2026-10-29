from __future__ import annotations
import base64
import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock
import httpx
import pytest


def runtime_module(name):
    path = Path(__file__).resolve().parents[1] / "src/openapi_modular_cli/templates/runtime" / (name + ".py")
    spec = importlib.util.spec_from_file_location("openapi_modular_cli.templates.runtime." + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


auth = runtime_module("auth")
adapter = runtime_module("adapter")


def test_token_cache():
    hits = []
    def handler(request):
        hits.append(request)
        assert request.url.path == "/token"
        assert "grant_type=client_credentials" in request.content.decode()
        assert "scope=users%3Aread" in request.content.decode()
        expected = base64.b64encode(b"id:secret").decode()
        assert request.headers["authorization"] == "Basic " + expected
        return httpx.Response(200, json={"access_token": "OK", "expires_in": 3600, "token_type": "Bearer"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        provider = auth.OAuth2TokenProvider(token_url="https://auth.invalid/token", client_id="id",
            client_secret="secret", scope="users:read", http_client=http_client)
        assert provider.get_token() == "OK"
        assert provider.get_token() == "OK"
    assert len(hits) == 1


def test_no_cache_if_expiry_missing():
    count = []
    def handler(request):
        count.append(1)
        return httpx.Response(200, json={"access_token": "T"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        provider = auth.OAuth2TokenProvider(token_url="https://auth.invalid/token", client_id="id",
            client_secret="secret", http_client=http_client)
        provider.get_token(); provider.get_token()
    assert len(count) == 2


def test_auth_rejects_wrong_token_type():
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200,
         json={"access_token": "T", "token_type": "MAC"}))) as c:
        provider = auth.OAuth2TokenProvider(token_url="https://auth.invalid/token", client_id="id",
            client_secret="secret", http_client=c)
        with pytest.raises(ValueError, match="Bearer"):
            provider.get_token()


def test_match_templated_path():
    mapping = {("GET", "/users/{id}"): [{"Basic": []}]}
    assert adapter._matching_requirements(mapping, "GET", "/users/42") == [{"Basic": []}]


def test_basic_header_injected_in_adapter():
    class Configuration:
        def __init__(self, host): self.host = host
    class ApiClient:
        def __init__(self, configuration): self.configuration = configuration
        def update_params_for_auth(self, headers, queries, auth_settings, *args, **kwargs):
            assert auth_settings == []
    class Api:
        def __init__(self, client): self.api_client = client
    parent = Mock(host="https://api.invalid", auth=auth.BasicCredentials("u", "p"))
    api = adapter.build_domain_api(parent, Configuration, ApiClient, Api,
        schemes={"Basic": "basic"}, operation_security={("GET", "/users"): [{"Basic": []}]})
    headers = {}
    api.api_client.update_params_for_auth(headers, [], ["Basic"], "/users", "GET", None)
    assert headers["Authorization"] == "Basic " + base64.b64encode(b"u:p").decode()
    parent.register_generated_client.assert_called_once()


def test_auth_mode_mismatch_fails():
    class Configuration:
        def __init__(self, host): self.host=host
    class ApiClient:
        def __init__(self, configuration): self.configuration=configuration
    class Api:
        def __init__(self, client): self.api_client=client
    parent = Mock(host="https://api.invalid", auth=None)
    api = adapter.build_domain_api(parent, Configuration, ApiClient, Api,
        schemes={"Basic": "basic"}, operation_security={("GET", "/users"): [{"Basic": []}]})
    with pytest.raises(adapter.AuthenticationModeError):
        api.api_client.update_params_for_auth({}, [], ["Basic"], "/users", "GET", None)


def test_oauth_header_not_sent_to_public_operation():
    class Configuration:
        def __init__(self, host): self.host=host
    class ApiClient:
        def __init__(self, configuration): self.configuration=configuration
        def update_params_for_auth(self, headers, queries, auth_settings, *args, **kwargs):
            assert not auth_settings
    class Api:
        def __init__(self, client): self.api_client=client
    class Provider:
        def get_token(self):
            raise AssertionError("No se debe pedir un token para operación pública")
    parent = Mock(host="https://api.invalid", auth=auth.OAuthCredentials(Provider()))
    api = adapter.build_domain_api(parent, Configuration, ApiClient, Api,
        schemes={"OAuth": "oauth2"}, operation_security={("GET", "/health"): []})
    headers = {}
    api.api_client.update_params_for_auth(headers, [], ["OAuth"], "/health", "GET", None)
    assert "Authorization" not in headers


def test_oauth_header_injected_for_secured_endpoint():
    class Configuration:
        def __init__(self, host): self.host=host
    class ApiClient:
        def __init__(self, configuration): self.configuration=configuration
        def update_params_for_auth(self, headers, queries, auth_settings, *args, **kwargs):
            assert auth_settings == []
    class Api:
        def __init__(self, client): self.api_client=client
    class Provider:
        def get_token(self): return "my-token"
    parent = Mock(host="https://api.invalid", auth=auth.OAuthCredentials(Provider()))
    api = adapter.build_domain_api(parent, Configuration, ApiClient, Api,
        schemes={"OAuth": "oauth2"}, operation_security={("GET", "/users"): [{"OAuth": ["read"]}]})
    headers = {}
    api.api_client.update_params_for_auth(headers, [], ["OAuth"], "/users", "GET", None)
    assert headers["Authorization"] == "Bearer my-token"
