from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_CONFIG_FILE = ROOT / "config" / "broker.example.yaml"
SCHEMA_FILE = ROOT / "config" / "broker.schema.json"


def test_public_json_schema_exists_and_names_contract() -> None:
    import json

    loaded = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))

    assert loaded["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert loaded["$id"] == "https://mcp-broker.local/schema/broker.schema.json"
    assert loaded["title"] == "mcp-broker config"
    assert loaded["properties"]["schema_version"]["const"] == 1
    assert loaded["additionalProperties"] is False


def test_config_validate_accepts_public_example() -> None:
    from mcp_broker.config_validate import validate_config_file

    result = validate_config_file(PUBLIC_CONFIG_FILE, SCHEMA_FILE)

    assert result.config_path == PUBLIC_CONFIG_FILE
    assert result.schema_path == SCHEMA_FILE
    assert result.ok is True


def test_config_validate_rejects_unknown_keys_before_runtime_load(tmp_path: Path) -> None:
    from mcp_broker.config_validate import ConfigValidationError, validate_config_file

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        """
schema_version: 1
runtime:
  root: /tmp/mcp-broker-test
broker: {}
upstreams:
  read-store:
    command: read-store
    unexpected_private_fixture: true
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError) as raised:
        validate_config_file(config_file, SCHEMA_FILE)

    assert "schema validation failed" in str(raised.value)
    assert "upstreams.read-store" in str(raised.value)
    assert "unexpected_private_fixture" in str(raised.value)


def test_config_validate_rejects_session_env_without_per_session_mode(tmp_path: Path) -> None:
    from mcp_broker.config_validate import ConfigValidationError, validate_config_file

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        """
schema_version: 1
runtime:
  root: /tmp/mcp-broker-test
upstreams:
  session-tool:
    command: session-tool
    mode: shared
    session_env:
      PROJECT_DIR: client_cwd
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError) as raised:
        validate_config_file(config_file, SCHEMA_FILE)

    assert "schema validation failed" in str(raised.value)
    assert "upstreams.session-tool.mode" in str(raised.value)
    assert "per_session" in str(raised.value)


def test_config_validate_reports_runtime_loader_errors(tmp_path: Path) -> None:
    from mcp_broker.config_validate import ConfigValidationError, validate_config_file

    config_file = tmp_path / "broker.yaml"
    config_file.write_text(
        """
schema_version: 1
runtime:
  root: /tmp/mcp-broker-test
broker: {}
profiles:
  codex:
    max_tools: 80
    compact_tools_enabled: true
upstreams:
  writer:
    command: writer
    profiles:
      - codex
    mutating: true
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError) as raised:
        validate_config_file(config_file, SCHEMA_FILE)

    assert "loader validation failed" in str(raised.value)
    assert "mutating upstream writer requires profile allowlist entry: codex" in str(raised.value)


def test_config_validate_rejects_non_object_schema_and_config(tmp_path: Path) -> None:
    from mcp_broker.config_validate import ConfigValidationError, validate_config_file

    schema_file = tmp_path / "schema.json"
    schema_file.write_text("[]", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="schema file must contain a JSON object"):
        validate_config_file(PUBLIC_CONFIG_FILE, schema_file)

    config_file = tmp_path / "broker.yaml"
    config_file.write_text("[]", encoding="utf-8")

    with pytest.raises(ConfigValidationError, match="config file must contain a YAML mapping"):
        validate_config_file(config_file, SCHEMA_FILE)


def test_config_validate_main_reports_success_and_failure(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.config_validate import main

    assert main(["--config", str(PUBLIC_CONFIG_FILE), "--schema", str(SCHEMA_FILE)]) == 0
    captured = capsys.readouterr()
    assert "config validated:" in captured.out
    assert str(PUBLIC_CONFIG_FILE) in captured.out

    bad_config = tmp_path / "bad.yaml"
    bad_config.write_text("[]", encoding="utf-8")

    assert main(["--config", str(bad_config), "--schema", str(SCHEMA_FILE)]) == 1
    captured = capsys.readouterr()
    assert "config file must contain a YAML mapping" in captured.out
