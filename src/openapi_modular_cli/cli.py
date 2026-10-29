\
"""Interfaz de comandos para generar SDKs Python modulares desde OpenAPI."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import subprocess
from . import __version__
from .build import build
from .spec import discover_tags, load_spec, security_metadata, filtered_spec


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="openapi-modular", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    commands = p.add_subparsers(dest="action", required=True)
    i = commands.add_parser("inspect", help="Muestra tags y mecanismos de seguridad detectados")
    i.add_argument("--spec", type=Path, required=True)
    g = commands.add_parser("generate", help="Produce distribuciones Python + extras por tag")
    g.add_argument("--spec", type=Path, required=True)
    g.add_argument("--name", required=True, help="Nombre PyPI del SDK resultante, p.ej. api-sdk")
    g.add_argument("--module", default=None, help="Módulo Python público; por defecto derivado de --name")
    g.add_argument("--output", type=Path, required=True)
    g.add_argument("--package-version", default="0.1.0")
    g.add_argument("--generator", default="openapi-generator-cli", help="Ruta al ejecutable OpenAPI Generator")
    g.add_argument("--scaffold-only", action="store_true", help="No invoca OpenAPI Generator: solo planificación, NO instalable")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.action == "inspect":
            spec = load_spec(args.spec)
            tags = discover_tags(spec)
            security = {}
            for slug, tag in tags.items():
                filtered = filtered_spec(spec, tag)
                schemes, _ = security_metadata(filtered)
                security[slug] = schemes
            print(json.dumps({"tags": tags, "securitySchemes": security}, indent=2, ensure_ascii=False))
            return 0
        tags = build(args.spec, output=args.output, distribution=args.name,
            module=args.module, version=args.package_version,
            generator=args.generator, scaffold_only=args.scaffold_only)
        print(f"Generación finalizada: {len(tags)} extras en {args.output}")
        if args.scaffold_only:
            print("ATENCIÓN: salida de previsualización sin código HTTP; NO es instalable")
        return 0
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
