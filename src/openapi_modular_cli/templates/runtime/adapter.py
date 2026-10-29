"""Adaptador para clases generadas por OpenAPI Generator con library=urllib3.

Se mantiene fuera del árbol generado. Compatibilidad comprobable para el
método update_params_for_auth() de la plantilla de Python urllib3 7.x.
"""
from __future__ import annotations

import base64
import re
from typing import Any

from .auth import BasicCredentials, OAuthCredentials


class AuthenticationModeError(RuntimeError):
    pass


def _matching_requirements(
    security: dict[tuple[str, str], list[dict[str, list[str]]]],
    method: str,
    resource_path: str,
) -> list[dict[str, list[str]]] | None:
    # resource_path llega habitualmente con los parámetros de ruta sustituidos.
    for (verb, template), requirements in security.items():
        if verb != method.upper():
            continue
        expression = "^" + re.sub(r"\\\{[^{}]+\\\}", r"[^/]+", re.escape(template)) + "$"
        if re.fullmatch(expression, resource_path.split("?", 1)[0]):
            return requirements
    return None


def build_domain_api(
    parent: Any,
    configuration_cls: type,
    api_client_cls: type,
    api_cls: type,
    *,
    schemes: dict[str, str],
    operation_security: dict[tuple[str, str], list[dict[str, list[str]]]],
) -> Any:
    """Instancia la API con credenciales elegidas operación a operación.

    El mapa security respeta la semántica OpenAPI: elementos de la lista = OR;
    varios mecanismos en un mismo objeto = AND (no soportado en este MVP).
    """
    config = configuration_cls(host=parent.host)
    selected_auth = parent.auth

    class SecuredGeneratedApiClient(api_client_cls):
        def update_params_for_auth(
            self,
            headers,
            queries,
            auth_settings,
            resource_path,
            method,
            body,
            request_auth=None,
        ):
            if request_auth is not None:
                return super().update_params_for_auth(
                    headers, queries, auth_settings, resource_path, method, body,
                    request_auth=request_auth,
                )
            choices = _matching_requirements(operation_security, method, resource_path)
            if choices is None:
                # Una operación no esperada no recibe credenciales automáticamente.
                raise AuthenticationModeError(
                    f"Operación no incluida en el manifiesto: {method} {resource_path}"
                )
            if not choices or {} in choices:
                # Pública: ignorar cualquier auth_setting que el generador añada.
                return super().update_params_for_auth(
                    headers, queries, [], resource_path, method, body,
                    request_auth=None,
                )
            candidate_names = []
            for requirement in choices:
                if len(requirement) != 1:
                    raise AuthenticationModeError(
                        "Los esquemas de autenticación combinados (AND) no se admiten"
                    )
                name = next(iter(requirement))
                candidate_names.append(name)
                kind = schemes.get(name)
                if kind == "basic" and isinstance(selected_auth, BasicCredentials):
                    encoded = base64.b64encode(
                        f"{selected_auth.username}:{selected_auth.password}".encode("utf-8")
                    ).decode("ascii")
                    headers["Authorization"] = f"Basic {encoded}"
                    break
                if kind == "oauth2" and isinstance(selected_auth, OAuthCredentials):
                    headers["Authorization"] = f"Bearer {selected_auth.provider.get_token()}"
                    break
            else:
                raise AuthenticationModeError(
                    f"La operación {method} {resource_path} exige {candidate_names}; "
                    "el tipo de autenticación configurado no es compatible"
                )
            # No permitir que el runtime generado sobrescriba Authorization.
            return super().update_params_for_auth(
                headers, queries, [], resource_path, method, body,
                request_auth=None,
            )

    generated_client = SecuredGeneratedApiClient(configuration=config)
    parent.register_generated_client(generated_client)
    return api_cls(generated_client)
