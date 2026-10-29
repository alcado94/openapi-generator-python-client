from __future__ import annotations
import json
from pathlib import Path
import tomllib
import pytest
from openapi_modular_cli.build import build, _valid_names
from openapi_modular_cli.cli import main


def fake_runner(args, *, check):
    assert check
    assert "-g" in args
    assert args[args.index("-g")+1] == "python"
    assert "library=urllib3" in args[args.index("--additional-properties")+1]
    props = dict(p.split("=", 1) for p in args[args.index("--additional-properties")+1].split(","))
    pkg = props["packageName"]
    tag_slug = pkg.removesuffix("_generated").split("_")[-1]
    dest = Path(args[args.index("-o")+1])
    source = dest / "src" / pkg
    source.mkdir(parents=True)
    (source / "__init__.py").write_text("", encoding="utf-8")
    (source / "configuration.py").write_text("class Configuration:\n    pass\n", encoding="utf-8")
    (source / "api_client.py").write_text("class ApiClient:\n    pass\n", encoding="utf-8")
    api = source / "api"
    api.mkdir()
    (api / "__init__.py").write_text("", encoding="utf-8")
    api_name = tag_slug.title() + "Api"
    (api / (tag_slug + "_api.py")).write_text(f"class {api_name}:\n    pass\n", encoding="utf-8")
    (dest / "requirements.txt").write_text("urllib3>=2.1,<3\npydantic>=2.10,<3\n", encoding="utf-8")


def test_full_generate_uses_runner(spec_file, tmp_path):
    target = tmp_path / "output"
    tags = build(spec_file, output=target, distribution="api-suite", version="1.2.3", runner=fake_runner)
    assert set(tags) == {"catalogs", "users"}
    facade = tomllib.loads((target / "packages/api-suite/pyproject.toml").read_text())
    assert set(facade["project"]["optional-dependencies"]) == {"catalogs", "users", "all"}
    assert facade["project"]["optional-dependencies"]["users"] == ["api-suite-users==1.2.3"]
    assert (target / "packages/api-suite-users/src/api_suite_users_generated/api/users_api.py").exists()
    assert "api_suite.domains" in (target / "packages/api-suite-users/pyproject.toml").read_text()
    assert (target / "packages/api-suite-core/src/api_suite_core/auth.py").exists()
    assert (target / "manifest.json").exists()
    assert not (target / ".generator-work").exists()


def test_generated_project_names_are_dynamic(spec_file, tmp_path):
    target = tmp_path / "out"
    build(spec_file, output=target, distribution="otra-lib", module="client_interno", scaffold_only=True)
    assert (target / "packages/otra-lib-core/src/client_interno_core/client.py").exists()
    assert (target / "packages/otra-lib/src/client_interno/__init__.py").exists()
    assert tomllib.loads((target / "packages/otra-lib/pyproject.toml").read_text())["project"]["name"] == "otra-lib"


def test_nonempty_output_rejected(spec_file, tmp_path):
    target = tmp_path / "out"
    target.mkdir()
    (target / "important.txt").write_text("no borrar")
    with pytest.raises(FileExistsError):
        build(spec_file, output=target, distribution="un-sdk", scaffold_only=True)
    assert (target / "important.txt").read_text() == "no borrar"


def test_inspect_cli_outputs_json(spec_file, capsys):
    assert main(["inspect", "--spec", str(spec_file)]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["tags"]["users"] == "Users"
    assert data["securitySchemes"]["catalogs"]["OAuth"] == "oauth2"


def test_invalid_dist():
    with pytest.raises(ValueError):
        _valid_names("_bad-", None)
