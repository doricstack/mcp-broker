from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_daemon_write_log_signature_uses_body_owned_default_level() -> None:
    import mcp_broker.daemon_status as daemon_status

    level_parameter = inspect.signature(daemon_status.BrokerDaemonStatusMixin._write_log).parameters[
        "level"
    ]

    assert level_parameter.default is None
    assert daemon_status._DEFAULT_LOG_LEVEL == "info"


def test_daemon_write_log_persists_compact_sorted_redacted_jsonl(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.daemon_status as daemon_status
    from mcp_broker.daemon import BrokerDaemon

    monkeypatch.setattr(daemon_status.os, "getpid", lambda: 321)
    monkeypatch.setattr(daemon_status, "_utc_timestamp", lambda: "2026-06-07T07:00:00+00:00")
    daemon = BrokerDaemon(runtime_root=tmp_path / "runtime", socket_path=tmp_path / "broker.sock")

    daemon._write_log(
        "audit.event",
        level="warning",
        safe="keep",
        token="secret-token",
    )

    assert daemon.log_path.read_text(encoding="utf-8") == (
        '{"event":"audit.event","level":"warning","pid":321,"safe":"keep",'
        '"token":"[redacted]","ts":"2026-06-07T07:00:00+00:00"}\n'
    )


def test_daemon_write_log_uses_default_info_level_and_utf8_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.daemon_status as daemon_status
    from mcp_broker.daemon import BrokerDaemon

    append_calls: list[tuple[str, str | None]] = []
    original_open = Path.open

    def open_spy(self: Path, mode: str = "r", *args: object, **kwargs: object) -> object:
        if self.name == "broker.jsonl" and mode == "a":
            append_calls.append((mode, kwargs.get("encoding")))
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_spy)
    monkeypatch.setattr(daemon_status.os, "getpid", lambda: 432)
    monkeypatch.setattr(daemon_status, "_utc_timestamp", lambda: "2026-06-07T07:10:00+00:00")
    daemon = BrokerDaemon(runtime_root=tmp_path / "runtime", socket_path=tmp_path / "broker.sock")

    daemon._write_log("default.level")

    assert append_calls == [("a", "utf-8")]
    assert _read_jsonl(daemon.log_path) == [
        {
            "event": "default.level",
            "level": "info",
            "pid": 432,
            "ts": "2026-06-07T07:10:00+00:00",
        }
    ]


def test_daemon_request_log_records_ok_error_and_notification_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.daemon_status as daemon_status
    from mcp_broker.daemon import BrokerDaemon

    timestamps = iter(
        [
            "2026-06-07T07:00:00+00:00",
            "2026-06-07T07:00:01+00:00",
            "2026-06-07T07:00:02+00:00",
            "2026-06-07T07:00:03+00:00",
            "2026-06-07T07:00:04+00:00",
            "2026-06-07T07:00:05+00:00",
            "2026-06-07T07:00:06+00:00",
            "2026-06-07T07:00:07+00:00",
        ]
    )
    monkeypatch.setattr(daemon_status.os, "getpid", lambda: 654)
    monkeypatch.setattr(daemon_status, "_utc_timestamp", lambda: next(timestamps))
    daemon = BrokerDaemon(runtime_root=tmp_path / "runtime", socket_path=tmp_path / "broker.sock")
    daemon._started_at = "2026-06-07T06:59:59+00:00"

    daemon._write_request_log("req-1", "tools/list", {"result": {"tools": []}})
    daemon._write_request_log(2, "tools/call", {"error": {"code": -32000}})
    daemon._write_request_log("req-err-2", "tools/call", {"error": {"code": -32001}})
    daemon._write_request_log({"not": "jsonrpc-id"}, 123, None)

    records = _read_jsonl(daemon.log_path)
    snapshot = json.loads(daemon.status_snapshot_path.read_text(encoding="utf-8"))

    assert [record["event"] for record in records] == [
        "request.handled",
        "request.handled",
        "request.handled",
        "request.handled",
    ]
    assert records[0] == {
        "event": "request.handled",
        "level": "info",
        "method": "tools/list",
        "pid": 654,
        "request_id": "req-1",
        "status": "ok",
        "ts": "2026-06-07T07:00:00+00:00",
    }
    assert records[1]["method"] == "tools/call"
    assert records[1]["request_id"] == 2
    assert records[1]["status"] == "error"
    assert records[2]["method"] == "tools/call"
    assert records[2]["request_id"] == "req-err-2"
    assert records[2]["status"] == "error"
    assert records[3]["method"] is None
    assert records[3]["request_id"] is None
    assert records[3]["status"] == "notification"
    assert daemon._requests_total == 4
    assert daemon._request_errors_total == 2
    assert daemon._last_request_method is None
    assert daemon._last_request_status == "notification"
    assert snapshot == {
        "last_request_method": None,
        "last_request_status": "notification",
        "pid": 654,
        "request_errors_total": 2,
        "requests_total": 4,
        "socket_path": str(tmp_path / "broker.sock"),
        "started_at": "2026-06-07T06:59:59+00:00",
        "status": "running",
        "updated_at": "2026-06-07T07:00:07+00:00",
        "upstreams": {},
    }


def test_daemon_request_log_counts_only_error_responses(tmp_path: Path) -> None:
    from mcp_broker.daemon import BrokerDaemon

    daemon = BrokerDaemon(runtime_root=tmp_path / "runtime", socket_path=tmp_path / "broker.sock")

    daemon._write_request_log("req-ok", "tools/list", {"result": {"tools": []}})
    assert daemon._requests_total == 1
    assert daemon._request_errors_total == 0

    daemon._write_request_log("req-error", "tools/call", {"error": {"code": -32000}})
    assert daemon._requests_total == 2
    assert daemon._request_errors_total == 1

    daemon._write_request_log("req-notification", "notifications/initialized", None)
    assert daemon._requests_total == 3
    assert daemon._request_errors_total == 1


def test_daemon_status_snapshot_uses_config_state_dir_and_replaces_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.daemon_status as daemon_status
    from mcp_broker.daemon import BrokerDaemon

    config = BrokerConfig(
        runtime=RuntimeConfig(
            root=tmp_path / "runtime",
            socket_path=tmp_path / "broker.sock",
            log_dir=tmp_path / "runtime" / "logs",
            state_dir=tmp_path / "custom-state",
            secrets_dir=tmp_path / "runtime" / "secrets",
        ),
        broker=BrokerSettings(),
        upstreams={},
    )
    monkeypatch.setattr(daemon_status.os, "getpid", lambda: 987)
    monkeypatch.setattr(daemon_status, "_utc_timestamp", lambda: "2026-06-07T08:00:00+00:00")
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    daemon._started_at = "2026-06-07T07:59:59+00:00"
    daemon._requests_total = 7
    daemon._request_errors_total = 2
    daemon._last_request_method = "broker/status"
    daemon._last_request_status = "error"

    daemon._write_status_snapshot("degraded")

    assert daemon.status_snapshot_path == tmp_path / "custom-state" / "broker-status.json"
    assert sorted(path.name for path in (tmp_path / "custom-state").iterdir()) == [
        "broker-status.json"
    ]
    assert json.loads(daemon.status_snapshot_path.read_text(encoding="utf-8")) == {
        "last_request_method": "broker/status",
        "last_request_status": "error",
        "pid": 987,
        "request_errors_total": 2,
        "requests_total": 7,
        "socket_path": str(tmp_path / "broker.sock"),
        "started_at": "2026-06-07T07:59:59+00:00",
        "status": "degraded",
        "updated_at": "2026-06-07T08:00:00+00:00",
        "upstreams": {},
    }


def test_daemon_status_snapshot_writes_sorted_utf8_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.daemon_status as daemon_status
    from mcp_broker.daemon import BrokerDaemon

    dumps_kwargs: list[dict[str, object]] = []
    write_calls: list[tuple[str, str | None]] = []
    original_dumps = daemon_status.json.dumps
    original_write_text = Path.write_text

    def dumps_spy(value: object, *args: object, **kwargs: object) -> str:
        dumps_kwargs.append(dict(kwargs))
        return original_dumps(value, *args, **kwargs)

    def write_text_spy(self: Path, data: str, *args: object, **kwargs: object) -> int:
        if self.name.startswith("broker-status.json.") and self.name.endswith(".tmp"):
            write_calls.append((data, kwargs.get("encoding")))
        return original_write_text(self, data, *args, **kwargs)

    monkeypatch.setattr(daemon_status.json, "dumps", dumps_spy)
    monkeypatch.setattr(Path, "write_text", write_text_spy)
    monkeypatch.setattr(daemon_status.os, "getpid", lambda: 988)
    monkeypatch.setattr(daemon_status, "_utc_timestamp", lambda: "2026-06-07T08:10:00+00:00")
    daemon = BrokerDaemon(runtime_root=tmp_path / "runtime", socket_path=tmp_path / "broker.sock")

    daemon._write_status_snapshot("running")

    assert len(write_calls) == 1
    assert write_calls[0][1] == "utf-8"
    assert dumps_kwargs == [{"sort_keys": True}]


def test_daemon_upstream_event_adds_upstream_name_and_redacts_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.daemon_status as daemon_status
    from mcp_broker.daemon import BrokerDaemon

    monkeypatch.setattr(daemon_status.os, "getpid", lambda: 111)
    monkeypatch.setattr(daemon_status, "_utc_timestamp", lambda: "2026-06-07T09:00:00+00:00")
    daemon = BrokerDaemon(runtime_root=tmp_path / "runtime", socket_path=tmp_path / "broker.sock")

    daemon._write_upstream_event(
        "upstream.ready",
        "example-upstream",
        {"pid": 222, "token": "secret-token"},
    )

    assert _read_jsonl(daemon.log_path) == [
        {
            "event": "upstream.ready",
            "level": "info",
            "pid": 222,
            "token": "[redacted]",
            "ts": "2026-06-07T09:00:00+00:00",
            "upstream": "example-upstream",
        }
    ]


def test_daemon_request_log_safely_forwards_request_fields_without_failure_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.daemon import BrokerDaemon

    daemon = BrokerDaemon(runtime_root=tmp_path / "runtime", socket_path=tmp_path / "broker.sock")
    forwarded: list[tuple[object, object, dict[str, object] | None]] = []
    failure_events: list[tuple[str, dict[str, object]]] = []

    def write_request_log_spy(
        request_id: object,
        method: object,
        response: dict[str, object] | None,
    ) -> None:
        forwarded.append((request_id, method, response))

    def write_log_spy(event: str, **fields: object) -> None:
        failure_events.append((event, fields))

    monkeypatch.setattr(daemon, "_write_request_log", write_request_log_spy)
    monkeypatch.setattr(daemon, "_write_log", write_log_spy)

    daemon._write_request_log_safely("req-3", "broker/status", {"result": {}})

    assert forwarded == [("req-3", "broker/status", {"result": {}})]
    assert failure_events == []


def test_daemon_request_log_safely_writes_error_event_when_snapshot_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.daemon_status as daemon_status
    from mcp_broker.daemon import BrokerDaemon

    monkeypatch.setattr(daemon_status.os, "getpid", lambda: 222)
    monkeypatch.setattr(daemon_status, "_utc_timestamp", lambda: "2026-06-07T10:00:00+00:00")
    daemon = BrokerDaemon(runtime_root=tmp_path / "runtime", socket_path=tmp_path / "broker.sock")

    def broken_snapshot(_status: str) -> None:
        raise RuntimeError("snapshot failed")

    monkeypatch.setattr(daemon, "_write_status_snapshot", broken_snapshot)

    daemon._write_request_log_safely("req-2", "tools/list", {"result": {}})

    records = _read_jsonl(daemon.log_path)
    assert records[0]["event"] == "request.handled"
    assert records[0]["status"] == "ok"
    assert records[1] == {
        "error": "snapshot failed",
        "event": "request.log_failed",
        "level": "error",
        "pid": 222,
        "ts": "2026-06-07T10:00:00+00:00",
    }
