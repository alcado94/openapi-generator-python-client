\
"""Orquestación reutilizable: spec -> generador externo -> ruedas por tag + extras."""
from __future__ import annotations
import argparse
import ast
from importlib.resources import files
import json
import keyword
from pathlib import Path
import pprint
import re
import shutil
import subprocess
from typing import Any, Callable
import yaml

from .spec import discover_tags, filtered_spec, load_spec, security_metadata, slugify

FALLBACK_REQUIREMENTS = [
    "urllib3>=2.1,<3", "python-dateutil>=2.8", "pydantic>=2.10,<3",
    "typing-extensions>=4.7", "certifi>=2024",
]


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _toml_literal(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def pyproject(name: str, version: str, deps: list[str], *, entrypoint: tuple[str, str, str] | None = None) -> str:
    lines = [
        "[build-system]", 'requires = ["setuptools>=68", "wheel"]',
        'build-backend = "setuptools.build_meta"', "",
        "[project]", f"name = {_toml_literal(name)}", f"version = {_toml_literal(version)}",
        'requires-python = ">=3.11"', "dependencies = [",
        *[f"  {_toml_literal(dep)}," for dep in deps], "]", "",
        "[tool.setuptools.packages.find]", 'where = ["src"]', "",
    ]
    if entrypoint:
        group, extra, module = entrypoint
        lines.extend([f"[project.entry-points.{_toml_literal(group)}]", f"{_toml_literal(extra)} = {_toml_literal(module + ':factory')}", ""])
    return "\n".join(lines)


def _requirements(generated_dir: Path) -> list[str]:
    source = generated_dir / "requirements.txt"
    if not source.exists():
        return FALLBACK_REQUIREMENTS.copy()
    result = []
    for line in source.read_text(encoding="utf-8").splitlines():
        dep = line.partition("#")[0].strip()
        if dep and not dep.startswith("-"):
            result.append(dep)
    return result or FALLBACK_REQUIREMENTS.copy()


def _api_class(pkg: Path) -> tuple[str, str]:
    found = []
    for path in sorted((pkg / "api").glob("*_api.py")):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            if isinstance(node, ast.ClassDef) and node.name.endswith("Api"):
                found.append((path.stem, node.name))
    if len(found) != 1:
        raise RuntimeError(f"Se esperaba una clase API por tag en {pkg}; encontradas: {found}")
    return found[0]


def _template(name: str) -> str:
    return (files("openapi_modular_cli") / "templates" / "runtime" / name).read_text(encoding="utf-8")


def _valid_names(distribution: str, module: str | None) -> tuple[str, str]:
    distribution = distribution.lower().replace("_", "-")
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", distribution):
        raise ValueError("--name debe ser un nombre de distribución válido, p.ej. api-sdk")
    if module is None:
        module = distribution.replace("-", "_")
    if keyword.iskeyword(module) or not module.isidentifier() or not re.fullmatch(r"[a-z][a-z0-9_]*", module):
        raise ValueError("--module debe ser un identificador Python válido")
    return distribution, module


def _generate_domain(
    *, output: Path, spec: dict[str, Any], tag: str, slug: str,
    distribution: str, module: str, version: str, generator: str,
    scaffold_only: bool, runner: Callable[..., Any],
) -> None:
    domain_dist = f"{distribution}-{slug.replace('_', '-')}"
    domain_module = f"{module}_{slug}"
    generated_module = f"{domain_module}_generated"
    package = output / "packages" / domain_dist
    src = package / "src"
    spec_path = output / "specs" / f"{slug}.yaml"
    sub_spec = filtered_spec(spec, tag)
    schemes, operations = security_metadata(sub_spec)
    write_file(spec_path, yaml.safe_dump(sub_spec, allow_unicode=True, sort_keys=False))

    module_name, class_name = "<pending>", "<pending>"
    dependencies = FALLBACK_REQUIREMENTS.copy()
    if not scaffold_only:
        temp = output / ".generator-work" / slug
        args = [
            generator, "generate", "-i", str(spec_path), "-g", "python", "-o", str(temp),
            "--additional-properties",
            f"packageName={generated_module},projectName={domain_dist},packageVersion={version},library=urllib3,sourceFolder=src",
            "--global-property", "apiTests=false,modelTests=false,apiDocs=false,modelDocs=false",
        ]
        print(f"  OpenAPI Generator: {tag}", flush=True)
        runner(args, check=True)
        generated_pkg = temp / "src" / generated_module
        if not generated_pkg.is_dir():
            raise RuntimeError(f"No se encontró el paquete generado esperado: {generated_pkg}")
        shutil.copytree(generated_pkg, src / generated_module)
        module_name, class_name = _api_class(src / generated_module)
        dependencies = _requirements(temp)
    else:
        # Genera exclusivamente el plan y scaffolding; NO es un wheel ejecutable.
        module_name = f"{slug}_api"
        class_name = "".join(word.capitalize() for word in slug.split("_")) + "Api"

    adapter = f"""# Adaptador generado para el tag {tag!r}.
from {module}_core.adapter import build_domain_api
from {generated_module}.configuration import Configuration
from {generated_module}.api_client import ApiClient
from {generated_module}.api.{module_name} import {class_name}

SCHEMES = {pprint.pformat(schemes, sort_dicts=True)}
OPERATION_SECURITY = {pprint.pformat(operations, sort_dicts=True)}


def factory(parent):
    return build_domain_api(
        parent, Configuration, ApiClient, {class_name},
        schemes=SCHEMES, operation_security=OPERATION_SECURITY,
    )
"""
    write_file(src / domain_module / "__init__.py", adapter)
    required = list(dict.fromkeys([f"{distribution}-core=={version}", *dependencies]))
    write_file(package / "pyproject.toml", pyproject(domain_dist, version, required,
        entrypoint=(f"{module}.domains", slug, domain_module)))
    write_file(package / "README.md", f"# {domain_dist}\n\nDistribución generada para tag `{tag}`; extra: `{distribution}[{slug}]`.\n")


def _generate_shared(output: Path, tags: dict[str, str], distribution: str, module: str, version: str) -> None:
    core_dist = f"{distribution}-core"
    core_module = f"{module}_core"
    core = output / "packages" / core_dist
    core_src = core / "src" / core_module
    for name in ("client.py", "adapter.py", "auth.py"):
        write_file(core_src / name, _template(name))
    write_file(core_src / "__init__.py", f"from .client import Client\n__all__ = ['Client']\n")
    write_file(core_src / "known_domains.py",
        f"KNOWN_DOMAINS = {tuple(tags)!r}\nENTRYPOINT_GROUP = {module + '.domains'!r}\nDIST_NAME = {distribution!r}\n")
    write_file(core / "pyproject.toml", pyproject(core_dist, version, ["httpx>=0.27,<1"]))

    facade = output / "packages" / distribution
    facade_src = facade / "src" / module
    write_file(facade_src / "__init__.py", f"from {core_module} import Client\n__all__ = ['Client']\n")
    write_file(facade_src / "py.typed", "")
    stubs = ["from typing import Any", "", "class Client:"]
    for slug in tags:
        stubs.append(f"    {slug}: Any")
    stubs.extend([
        '    @classmethod',
        '    def basic(cls, *, host: str, username: str, password: str) -> "Client": ...',
        '    @classmethod',
        '    def oauth2(cls, *, host: str, token_url: str, client_id: str, client_secret: str, scope: str = "") -> "Client": ...',
    ])
    write_file(facade_src / "__init__.pyi", "\n".join(stubs) + "\n")
    facade_deps = [f"{core_dist}=={version}"]
    config = pyproject(distribution, version, facade_deps)
    config += "[project.optional-dependencies]\n"
    for slug in tags:
        config += f"{slug} = [{_toml_literal(distribution + '-' + slug.replace('_','-') + '==' + version)}]\n"
    config += "all = [\n"
    for slug in tags:
        config += f"  {_toml_literal(distribution + '-' + slug.replace('_','-') + '==' + version)},\n"
    config += "]\n"
    write_file(facade / "pyproject.toml", config)


def build(
    spec_path: Path, *, output: Path, distribution: str,
    module: str | None = None, version: str = "0.1.0",
    generator: str = "openapi-generator-cli", scaffold_only: bool = False,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, str]:
    distribution, module = _valid_names(distribution, module)
    spec = load_spec(spec_path)
    tags = discover_tags(spec)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"El directorio de salida no está vacío: {output}. Usa otro directorio.")
    output.mkdir(parents=True, exist_ok=True)
    _generate_shared(output, tags, distribution, module, version)
    for slug, tag in tags.items():
        _generate_domain(
            output=output, spec=spec, tag=tag, slug=slug, distribution=distribution,
            module=module, version=version, generator=generator,
            scaffold_only=scaffold_only, runner=runner,
        )
    write_file(output / "manifest.json", json.dumps({
        "distribution": distribution, "module": module, "version": version,
        "tags": tags, "scaffold_only": scaffold_only, "library": "urllib3",
    }, indent=2, ensure_ascii=False) + "\n")
    generated = output / ".generator-work"
    if generated.exists():
        shutil.rmtree(generated)
    return tags
