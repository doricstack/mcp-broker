import json
from pathlib import Path

import pytest

from mcp_broker.cli import main as cli_main


pytestmark = pytest.mark.journey


def test_config_compose_cli_outputs_effective_config_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    org_path = _write_json(
        tmp_path / "org.json",
        {
            "clients": {"codex": {"command": "mcp-broker-client"}},
            "upstreams": {
                "github": {
                    "enabled": False,
                    "env": {"GITHUB_TOKEN": {"secret_ref": "GITHUB_TOKEN"}},
                }
            },
        },
    )
    team_path = _write_json(
        tmp_path / "team.json",
        {"upstreams": {"github": {"enabled": True}}},
    )
    add_on_path = _write_json(
        tmp_path / "audit.json",
        {"policy": {"audit": {"enabled": True}}},
    )
    user_path = _write_json(
        tmp_path / "user.json",
        {"clients": {"codex": {"command": "team-mcp-broker-client"}}},
    )

    result = cli_main(
        [
            "config",
            "compose",
            "--org",
            str(org_path),
            "--team",
            str(team_path),
            "--addon",
            str(add_on_path),
            "--user",
            str(user_path),
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["changed_runtime_state"] is False
    assert payload["effective_config_digest"].startswith("sha256:")
    assert payload["layers"] == ["org", "team", "audit", "user"]
    assert payload["effective_config"] == {
        "clients": {"codex": {"command": "team-mcp-broker-client"}},
        "policy": {"audit": {"enabled": True}},
        "upstreams": {
            "github": {
                "enabled": True,
                "env": {"GITHUB_TOKEN": {"secret_ref": "GITHUB_TOKEN"}},
            }
        },
    }
    assert payload["conflicts"] == [
        {
            "path": "upstreams.github.enabled",
            "previous_layer": "org",
            "new_layer": "team",
        },
        {
            "path": "clients.codex.command",
            "previous_layer": "org",
            "new_layer": "user",
        },
    ]
    assert "plain-secret-value" not in json.dumps(payload)


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path
