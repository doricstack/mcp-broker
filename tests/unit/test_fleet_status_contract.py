from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_broker.cli import main as cli_main


pytestmark = [pytest.mark.unit]


def _status_snapshot() -> dict[str, object]:
    return {
        "identity": {
            "active_profile": None,
            "active_profiles": ["codex", "ops"],
            "broker_id": "engineer-laptop",
            "bundle_version": "bundle-2026.07.01",
            "environment": "local",
            "schema_version": 1,
        },
        "last_request_method": "tools/call",
        "last_request_status": "ok",
        "pid": 321,
        "request_errors_total": 2,
        "requests_total": 22,
        "socket_path": "${HOME}/mcp/mcp-broker/sockets/broker.sock",
        "started_at": "2026-07-01T12:00:00+00:00",
        "status": "running",
        "updated_at": "2026-07-01T12:03:00+00:00",
        "upstreams": {
            "mail-prod": {
                "account": "engineer@example.com",
                "auth_state": "authenticated",
                "client_secret": "secret-value",
                "enabled": True,
                "env": {"TOKEN": "secret-token"},
                "last_error": "${HOME}/.config/token.json expired for engineer@example.com",
                "mode": "shared",
                "mutating": True,
                "pid": 654,
                "restarts": 1,
                "state": "running",
                "transport": "stdio",
            },
            "read-api": {
                "auth_state": "unknown",
                "enabled": True,
                "last_error": None,
                "mode": "shared",
                "mutating": False,
                "pid": None,
                "restarts": 0,
                "state": "configured",
                "transport": "http",
                "url": "https://api.example.com/mcp",
            },
        },
    }


def test_export_fleet_status_redacts_local_and_secret_fields() -> None:
    from mcp_broker.fleet_status import export_fleet_status

    payload = export_fleet_status(_status_snapshot())

    assert payload == {
        "identity": {
            "active_profiles": ["codex", "ops"],
            "broker_id": "engineer-laptop",
            "bundle_version": "bundle-2026.07.01",
            "environment": "local",
            "schema_version": 1,
        },
        "health": {
            "last_request_status": "ok",
            "started_at": "2026-07-01T12:00:00+00:00",
            "status": "running",
            "updated_at": "2026-07-01T12:03:00+00:00",
        },
        "request_counters": {
            "request_errors_total": 2,
            "requests_total": 22,
        },
        "upstreams": {
            "mail-prod": {
                "auth_state": "authenticated",
                "enabled": True,
                "last_error": "[redacted]",
                "mode": "shared",
                "mutating": True,
                "restarts": 1,
                "state": "running",
                "transport": "stdio",
            },
            "read-api": {
                "auth_state": "unknown",
                "enabled": True,
                "last_error": None,
                "mode": "shared",
                "mutating": False,
                "restarts": 0,
                "state": "configured",
                "transport": "http",
            },
        },
    }
    rendered = json.dumps(payload, sort_keys=True)
    assert "${HOME}" not in rendered
    assert "engineer@example.com" not in rendered
    assert "secret-value" not in rendered
    assert "secret-token" not in rendered
    assert "https://api.example.com" not in rendered
    assert "socket_path" not in rendered
    assert "pid" not in rendered
    assert '"env":' not in rendered


def test_fleet_status_cli_exports_redacted_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    status_file = tmp_path / "broker-status.json"
    status_file.write_text(json.dumps(_status_snapshot()), encoding="utf-8")

    assert cli_main(["fleet-status", "export", "--status-file", str(status_file)]) == 0

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["identity"]["bundle_version"] == "bundle-2026.07.01"
    assert payload["request_counters"] == {
        "request_errors_total": 2,
        "requests_total": 22,
    }
    assert "${HOME}" not in output
    assert "engineer@example.com" not in output
    assert "secret" not in output
