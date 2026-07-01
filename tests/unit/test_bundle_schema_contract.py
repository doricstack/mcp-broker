import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from tests.support.repo_paths import repo_root


pytestmark = pytest.mark.unit

ROOT = repo_root()
BUNDLE_SCHEMA_FILE = ROOT / "config" / "broker.bundle.schema.json"


def test_bundle_schema_file_is_valid_json_schema() -> None:
    from mcp_broker.bundle_schema import load_bundle_schema

    schema = load_bundle_schema()

    assert BUNDLE_SCHEMA_FILE.exists()
    assert schema == json.loads(BUNDLE_SCHEMA_FILE.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def test_bundle_schema_accepts_minimal_desired_state_bundle() -> None:
    from mcp_broker.bundle_schema import load_bundle_schema

    validator = Draft202012Validator(load_bundle_schema())

    validator.validate(_minimal_bundle())


def test_bundle_schema_rejects_unknown_top_level_fields() -> None:
    from mcp_broker.bundle_schema import load_bundle_schema

    bundle = _minimal_bundle()
    bundle["install_script"] = "./setup.sh"

    with pytest.raises(ValidationError, match="Additional properties"):
        Draft202012Validator(load_bundle_schema()).validate(bundle)


def test_bundle_schema_rejects_remote_code_execution_policy() -> None:
    from mcp_broker.bundle_schema import load_bundle_schema

    bundle = _minimal_bundle()
    bundle["policy"]["allow_remote_code_execution"] = True

    with pytest.raises(ValidationError, match="False was expected"):
        Draft202012Validator(load_bundle_schema()).validate(bundle)


def test_bundle_schema_metadata_exposes_non_executable_contract() -> None:
    from mcp_broker.bundle_schema import bundle_schema_metadata

    metadata = bundle_schema_metadata()

    assert metadata == {
        "schema_file": str(BUNDLE_SCHEMA_FILE),
        "schema_version": 1,
        "required_sections": (
            "schema_version",
            "bundle_id",
            "version",
            "channel",
            "source",
            "checksum",
            "applies_to",
            "profiles",
            "upstreams",
            "clients",
            "policy",
            "compatibility",
        ),
        "executes_remote_code": False,
    }


def _minimal_bundle() -> dict[str, object]:
    return {
        "schema_version": 1,
        "bundle_id": "personal-local",
        "version": "2026.07.01",
        "channel": "stable",
        "source": {
            "type": "file",
            "uri": "file:///tmp/mcp-broker/bundles/personal-local.json",
            "created_by": "mcp-broker",
        },
        "checksum": {
            "algorithm": "sha256",
            "value": "0" * 64,
        },
        "applies_to": {
            "broker_id": "mcp-broker-local",
            "environments": ["local"],
        },
        "profiles": {
            "codex": {
                "max_tools": 80,
                "compact_tools_enabled": True,
                "broker_tool_name_style": "snake",
            },
        },
        "upstreams": {
            "catalog-cache": {
                "enabled": True,
                "mode": "shared",
                "transport": "stdio",
                "command": "catalog-cache-server",
                "profiles": ["codex"],
            },
        },
        "clients": {
            "codex": {
                "format": "codex-toml",
                "entry_name": "mcp-broker",
            },
        },
        "policy": {
            "approval_required": True,
            "allow_remote_code_execution": False,
            "mutating_upstreams_require_allowlist": True,
        },
        "compatibility": {
            "min_config_schema_version": 1,
            "max_config_schema_version": 1,
            "required_features": ["broker.identity"],
        },
    }
