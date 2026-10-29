"""Fachada pública compartida que descubre los subpaquetes instalados."""
from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from .auth import Auth, BasicCredentials, OAuth2TokenProvider, OAuthCredentials
from .known_domains import KNOWN_DOMAINS, ENTRYPOINT_GROUP, DIST_NAME


class Client:
    """Punto de entrada: client.users.get_users(), client.catalogs.get_colors()."""

    def __init__(self, *, host: str, auth: Auth = None) -> None:
        self.host = host.rstrip("/")
        self.auth = auth
        self._domains: dict[str, Any] = {}
        self._clients: list[Any] = []
        self._closed = False

    @classmethod
    def basic(cls, *, host: str, username: str, password: str) -> "Client":
        return cls(host=host, auth=BasicCredentials(username, password))

    @classmethod
    def oauth2(
        cls,
        *,
        host: str,
        token_url: str,
        client_id: str,
        client_secret: str,
        scope: str = "",
    ) -> "Client":
        return cls(
            host=host,
            auth=OAuthCredentials(
                OAuth2TokenProvider(
                    token_url=token_url,
                    client_id=client_id,
                    client_secret=client_secret,
                    scope=scope,
                )
            ),
        )

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or name not in KNOWN_DOMAINS:
            raise AttributeError(f"{type(self).__name__!s} no tiene el atributo {name!r}")
        if self._closed:
            raise RuntimeError("Este cliente ya está cerrado")
        if name in self._domains:
            return self._domains[name]
        eps = entry_points(group=ENTRYPOINT_GROUP)
        matches = [ep for ep in eps if ep.name == name]
        if not matches:
            raise ImportError(
                f"El módulo {name!r} no está instalado. "
                f'Ejecuta: pip install "{DIST_NAME}[{name}]"'
            )
        if len(matches) > 1:
            raise RuntimeError(f"Existe más de un plugin registrado para {name!r}")
        domain = matches[0].load()(self)
        self._domains[name] = domain
        return domain

    def register_generated_client(self, generated_client: Any) -> None:
        self._clients.append(generated_client)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for api_client in reversed(self._clients):
            close = getattr(api_client, "close", None)
            if callable(close):
                close()
            else:
                pool = getattr(getattr(api_client, "rest_client", None), "pool_manager", None)
                clear = getattr(pool, "clear", None)
                if callable(clear):
                    clear()
        if isinstance(self.auth, OAuthCredentials):
            self.auth.provider.close()

    def __enter__(self) -> "Client":
        if self._closed:
            raise RuntimeError("Este cliente ya está cerrado")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
