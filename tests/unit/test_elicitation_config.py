"""Approval relay is explicit and isolated from shared upstream state."""

from pathlib import Path

import pytest
import yaml

from mcp_broker.config import BrokerConfig
from mcp_broker.config_validate import validate_config_file

pytestmark = pytest.mark.unit


def test_schema_accepts_opt_in_approval_relay(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"runtime": {"root": str(tmp_path / "runtime")}, "upstreams": {"sample": {
        "command": "python", "mode": "per_session", "relay_elicitation": True}}}))
    schema = Path(__file__).resolve().parents[2] / "config/broker.schema.json"
    assert validate_config_file(path, schema).ok


@pytest.mark.parametrize("extra", [
    {"mode": "shared"}, {"mode": "per_session", "transport": "http"},
    {"mode": "per_session", "relay_elicitation": "true"},
])
def test_relay_rejects_unsafe_or_malformed_configuration(tmp_path, extra):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"upstreams": {"sample": {
        "command": "python", "relay_elicitation": True, **extra}}}))
    with pytest.raises(ValueError):
        BrokerConfig.from_file(path)
