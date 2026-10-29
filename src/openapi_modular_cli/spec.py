\
"""Inspección y filtrado de OpenAPI 3.x, sin dependencias de servicios externos."""
from __future__ import annotations
from copy import deepcopy
import keyword
from pathlib import Path
import re
from typing import Any, Iterator
import yaml

HTTP_METHODS = frozenset(("get", "put", "post", "delete", "options", "head", "patch", "trace"))
COMPONENT_REF = re.compile(r"^#/components/([^/]+)/([^/]+)$")


def load_spec(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"No existe la especificación: {path}")
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or not str(spec.get("openapi", "")).startswith("3."):
        raise ValueError("Solo se admiten especificaciones OpenAPI 3.x YAML/JSON")
    if not isinstance(spec.get("paths"), dict):
        raise ValueError("OpenAPI debe contener un objeto 'paths'")
    # Esta versión solo resuelve referencias internas: fallar explícitamente.
    list(iter_refs(spec))
    return spec


def slugify(name: str) -> str:
    if not isinstance(name, str):
        raise ValueError(f"Tag no válido: {name!r}")
    value = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    if not value or not value.isidentifier() or keyword.iskeyword(value) or value in {"all", "core"}:
        raise ValueError(f"Tag incompatible con un extra Python: {name!r}")
    return value


def discover_tags(spec: dict[str, Any]) -> dict[str, str]:
    results: dict[str, str] = {}
    for path, item in spec["paths"].items():
        if not isinstance(item, dict):
            raise ValueError(f"Path item inválido: {path}")
        for method, operation in item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            if not isinstance(operation, dict) or not operation.get("tags"):
                raise ValueError(f"Faltan tags en {method.upper()} {path}")
            for tag in operation["tags"]:
                slug = slugify(tag)
                if slug in results and results[slug] != tag:
                    raise ValueError(f"Colisión entre tags: {tag!r} y {results[slug]!r}")
                results[slug] = tag
    if not results:
        raise ValueError("La especificación no tiene operaciones con tags")
    return dict(sorted(results.items()))


def iter_refs(obj: Any) -> Iterator[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "$ref" and isinstance(v, str):
                if not v.startswith("#/components/"):
                    raise ValueError(f"Solo se admiten referencias #/components internas: {v}")
                yield v
            else:
                yield from iter_refs(v)
    elif isinstance(obj, list):
        for element in obj:
            yield from iter_refs(element)


def _required_schemes(spec: dict[str, Any]) -> set[str]:
    required = set()
    for path_item in spec["paths"].values():
        for method, op in path_item.items():
            if method.lower() in HTTP_METHODS:
                for alternative in op.get("security", spec.get("security", [])):
                    required.update(alternative)
    return required


def filtered_spec(spec: dict[str, Any], tag: str) -> dict[str, Any]:
    result = deepcopy(spec)
    result["paths"] = {}
    for path, item in spec["paths"].items():
        kept = {k: deepcopy(v) for k, v in item.items() if k.lower() not in HTTP_METHODS}
        for method, operation in item.items():
            if method.lower() in HTTP_METHODS and tag in operation.get("tags", []):
                selected = deepcopy(operation)
                selected["tags"] = [tag]
                kept[method] = selected
        if any(method.lower() in HTTP_METHODS for method in kept):
            result["paths"][path] = kept
    if not result["paths"]:
        raise ValueError(f"Tag sin operaciones: {tag}")

    components = spec.get("components", {})
    selected_components: dict[str, dict[str, Any]] = {}
    pending = list(iter_refs(result["paths"]))
    # Las refs en seguridad suelen ser nombres de securitySchemes, no $ref.
    needed_schemes = _required_schemes(result)
    for scheme in needed_schemes:
        val = components.get("securitySchemes", {}).get(scheme)
        if val is None:
            raise ValueError(f"securityScheme ausente: {scheme}")
        selected_components.setdefault("securitySchemes", {})[scheme] = deepcopy(val)
        pending.extend(iter_refs(val))
    seen: set[str] = set()
    while pending:
        ref = pending.pop()
        if ref in seen:
            continue
        seen.add(ref)
        match = COMPONENT_REF.fullmatch(ref)
        if not match:
            raise ValueError(f"Referencia JSON Pointer no soportada: {ref}")
        kind, key = match.groups()
        val = components.get(kind, {}).get(key)
        if val is None:
            raise ValueError(f"Componente inexistente: {ref}")
        selected_components.setdefault(kind, {})[key] = deepcopy(val)
        pending.extend(iter_refs(val))
    result["components"] = selected_components
    return result


def security_metadata(spec: dict[str, Any]):
    schemes = {}
    for name, value in spec.get("components", {}).get("securitySchemes", {}).items():
        if value.get("type") == "http" and str(value.get("scheme", "")).lower() == "basic":
            schemes[name] = "basic"
        elif value.get("type") == "oauth2" and "clientCredentials" in value.get("flows", {}):
            schemes[name] = "oauth2"
        else:
            raise ValueError(f"Seguridad no soportada en la v0.1: {name} ({value.get('type')})")
    operations = {}
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method.lower() not in HTTP_METHODS:
                continue
            choices = deepcopy(operation.get("security", spec.get("security", [])))
            for choice in choices:
                if not isinstance(choice, dict) or len(choice) > 1:
                    raise ValueError(f"La seguridad combinada (AND) no está soportada: {method} {path}")
                if any(s not in schemes for s in choice):
                    raise ValueError(f"SecurityScheme desconocido: {method} {path}")
            operations[(method.upper(), path)] = choices
    return schemes, operations
