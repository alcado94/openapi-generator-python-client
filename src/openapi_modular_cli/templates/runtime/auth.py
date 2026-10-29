"""Autenticación centralizada para los módulos generados del SDK."""
from __future__ import annotations

from dataclasses import dataclass
import time
from threading import Lock

import httpx


@dataclass(frozen=True)
class BasicCredentials:
    username: str
    password: str


class OAuth2TokenProvider:
    """Client credentials: obtiene un token y lo reutiliza hasta su expiración.

    Se usa HTTP Basic para autenticar el cliente en token_url, según RFC 6749.
    `http_client` permite inyectar MockTransport en las pruebas.
    """

    def __init__(
        self,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str = "",
        timeout: float = 10.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        if not token_url or not client_id or not client_secret:
            raise ValueError("token_url, client_id y client_secret son obligatorios")
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.timeout = timeout
        self._client = http_client or httpx.Client()
        self._owns_client = http_client is None
        self._lock = Lock()
        self._access_token: str | None = None
        self._expires_at = 0.0

    def get_token(self) -> str:
        with self._lock:
            if self._access_token and time.monotonic() < self._expires_at:
                return self._access_token
            data = {"grant_type": "client_credentials"}
            if self.scope:
                data["scope"] = self.scope
            response = self._client.post(
                self.token_url,
                data=data,
                auth=(self.client_id, self.client_secret),
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            if str(payload.get("token_type", "Bearer")).lower() != "bearer":
                raise ValueError("El proveedor OAuth devolvió un token que no es Bearer")
            token = payload.get("access_token")
            if not isinstance(token, str) or not token:
                raise ValueError("La respuesta OAuth no contiene access_token")
            ttl = float(payload.get("expires_in", 0))
            self._access_token = token
            # Si el proveedor omite expires_in, no se cachea el token.
            self._expires_at = time.monotonic() + max(0.0, ttl - min(30.0, ttl * 0.1))
            return token

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


@dataclass(frozen=True)
class OAuthCredentials:
    provider: OAuth2TokenProvider


Auth = BasicCredentials | OAuthCredentials | None
