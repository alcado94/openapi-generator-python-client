import copy
import pytest
from openapi_modular_cli.spec import discover_tags, filtered_spec, security_metadata, slugify, load_spec


def test_discover_tags(sample_spec):
    assert discover_tags(sample_spec) == {"catalogs": "Catalogs", "users": "Users"}


def test_filter_preserves_only_used_schemas(sample_spec):
    result = filtered_spec(sample_spec, "Users")
    assert set(result["paths"]) == {"/users"}
    assert set(result["components"]["schemas"]) == {"User"}
    assert set(result["components"]["securitySchemes"]) == {"Basic"}


def test_filter_preserves_security_metadata(sample_spec):
    schemes, endpoints = security_metadata(filtered_spec(sample_spec, "Catalogs"))
    assert schemes == {"OAuth": "oauth2"}
    assert endpoints[("GET", "/colors")] == [{"OAuth": ["read"]}]


def test_multi_tag_endpoint_duplicated(sample_spec):
    sample_spec["paths"]["/users"]["get"]["tags"] = ["Users", "Catalogs"]
    result = filtered_spec(sample_spec, "Catalogs")
    assert result["paths"]["/users"]["get"]["tags"] == ["Catalogs"]


def test_collision_fails(sample_spec):
    sample_spec["paths"]["/colors"]["get"]["tags"] = ["Users!"]
    with pytest.raises(ValueError, match="Colisión"):
        discover_tags(sample_spec)


def test_untagged_operation_fails(sample_spec):
    sample_spec["paths"]["/users"]["get"].pop("tags")
    with pytest.raises(ValueError, match="Faltan tags"):
        discover_tags(sample_spec)


def test_unsupported_reference_fails(spec_file):
    text = spec_file.read_text().replace("#/components/schemas/User", "./models.yaml#/User")
    spec_file.write_text(text)
    with pytest.raises(ValueError, match="referencias"):
        load_spec(spec_file)


def test_reject_unsupported_auth(sample_spec):
    sample_spec["paths"]["/users"]["get"]["security"] = [{"Key": []}]
    sample_spec["components"]["securitySchemes"]["Key"] = {"type": "apiKey", "name": "key", "in": "header"}
    with pytest.raises(ValueError, match="no soportada"):
        security_metadata(filtered_spec(sample_spec, "Users"))


def test_slug_reservations():
    with pytest.raises(ValueError):
        slugify("all")
    with pytest.raises(ValueError):
        slugify("123")
