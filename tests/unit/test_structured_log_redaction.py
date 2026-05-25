import json
from pathlib import Path

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def test_broker_structured_logs_redact_sensitive_values(tmp_path: Path) -> None:
    from mcp_broker.daemon import BrokerDaemon

    runtime_root = tmp_path / "runtime"
    daemon = BrokerDaemon(runtime_root=runtime_root, socket_path=tmp_path / "broker.sock")

    daemon._write_log(
        "redaction.test",
        access_id="acct_12345",
        arguments=["https://user:pass@example.invalid/db", "/workspace/private/project"],
        env={"API_TOKEN": "token-value"},
        nested={"socket_path": "/tmp/private.sock", "safe": "keep"},
        runtime_root="/workspace/mcp/mcp-broker",
        token="token-value",
        tuple_values=("https://token.example/path", "plain"),
    )

    raw_log = daemon.log_path.read_text(encoding="utf-8")
    record = json.loads(raw_log)

    assert "acct_12345" not in raw_log
    assert "token-value" not in raw_log
    assert "https://user:pass@example.invalid/db" not in raw_log
    assert "/workspace" not in raw_log
    assert "/tmp/private.sock" not in raw_log
    assert record["access_id"] == "[redacted]"
    assert record["arguments"] == ["[redacted:url]", "[redacted:path]"]
    assert record["env"] == "[redacted]"
    assert record["nested"] == {"safe": "keep", "socket_path": "[redacted:path]"}
    assert record["runtime_root"] == "[redacted:path]"
    assert record["token"] == "[redacted]"
    assert record["tuple_values"] == ["[redacted:url]", "plain"]


def test_daemon_helpers_process_exists_treats_permission_denied_as_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.daemon_helpers as daemon_helpers

    monkeypatch.setattr(
        daemon_helpers.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(PermissionError()),
    )

    assert daemon_helpers.process_exists(123) is True
