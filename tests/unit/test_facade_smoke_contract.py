import json
from argparse import Namespace
from pathlib import Path
import subprocess

import pytest

from mcp_broker.facade_smoke import (
    FacadeSmokeError,
    _call_payload,
    _describe_payload,
    _request_through_client,
    _run_smoke,
    _initialize_payload,
    _search_payload,
    _start_daemon_if_needed,
    _stop_smoke_session,
    _raise_on_error,
    _tools_list_payload,
    build_facade_smoke_report,
    parse_call_args,
)


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def test_parse_call_args_requires_json_object() -> None:
    assert parse_call_args('{"message":"hello"}') == {"message": "hello"}

    with pytest.raises(ValueError, match="call args must be a JSON object"):
        parse_call_args('["bad"]')


def test_facade_payload_helpers_build_expected_jsonrpc_messages() -> None:
    assert _initialize_payload()["method"] == "initialize"
    assert _tools_list_payload() == {
        "jsonrpc": "2.0",
        "id": "tools/list",
        "method": "tools/list",
    }
    assert _search_payload("read-store")["params"] == {
        "name": "broker.search_tools",
        "arguments": {"query": "read-store", "limit": 10},
    }
    assert _describe_payload("read-store.get_project_scope")["params"] == {
        "name": "broker.describe_tool",
        "arguments": {"name": "read-store.get_project_scope"},
    }
    assert _call_payload("read-store.get_project_scope", {})["params"] == {
        "name": "broker.call_tool",
        "arguments": {"name": "read-store.get_project_scope", "arguments": {}},
    }


def test_build_facade_smoke_report_summarizes_compact_facade_path() -> None:
    report = build_facade_smoke_report(
        profile="llm-profile",
        list_response={
            "result": {
                "tools": [
                    {"name": "broker.search_tools"},
                    {"name": "broker.call_tool"},
                    {"name": "broker.describe_tool"},
                ]
            }
        },
        search_response={
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"matches": [{"name": "fake.echo"}]}),
                    }
                ]
            }
        },
        describe_response={
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps({"tool": {"name": "fake.echo"}})}
                ]
            }
        },
        call_response={
            "id": "fake.echo",
            "result": {"content": [{"type": "text", "text": "hello"}]},
        },
        started_daemon=True,
    )

    assert report == {
        "profile": "llm-profile",
        "advertised_tools": [
            "broker.call_tool",
            "broker.describe_tool",
            "broker.search_tools",
        ],
        "search_hit_count": 1,
        "described_tool": "fake.echo",
        "called_tool": "fake.echo",
        "call_text": "hello",
        "started_daemon": True,
    }


def test_build_facade_smoke_report_rejects_upstream_error_content() -> None:
    with pytest.raises(FacadeSmokeError, match="fake.echo returned upstream error"):
        build_facade_smoke_report(
            profile="llm-profile",
            list_response={"result": {"tools": [{"name": "broker.call_tool"}]}},
            search_response={
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps({"matches": [{"name": "fake.echo"}]})}
                    ]
                }
            },
            describe_response={
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps({"tool": {"name": "fake.echo"}})}
                    ]
                }
            },
            call_response={
                "id": "fake.echo",
                "result": {"content": [{"type": "text", "text": "Error: missing value"}]},
            },
            started_daemon=False,
        )


def test_facade_smoke_main_reports_invalid_call_args(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import mcp_broker.facade_smoke as facade_smoke

    def raise_value_error(_args: object) -> dict:
        raise ValueError("call args must be a JSON object")

    monkeypatch.setattr(facade_smoke, "_run_smoke", raise_value_error)

    result = facade_smoke.main(
        [
            "--config",
            "/tmp/broker.yaml",
            "--query",
            "echo",
            "--call-tool",
            "fake.echo",
            "--call-args",
            "[]",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "call args must be a JSON object" in captured.err


def test_facade_start_daemon_accepts_existing_daemon() -> None:
    import mcp_broker.facade_smoke as facade_smoke

    class AlreadyRunningDaemon:
        def start(self) -> None:
            raise facade_smoke.BrokerDaemonError("broker daemon already running")

    assert facade_smoke._start_daemon_if_needed(AlreadyRunningDaemon()) is False


def test_facade_start_daemon_rethrows_unexpected_errors() -> None:
    import mcp_broker.facade_smoke as facade_smoke

    class BrokenDaemon:
        def start(self) -> None:
            raise facade_smoke.BrokerDaemonError("bind failed")

    with pytest.raises(facade_smoke.BrokerDaemonError, match="bind failed"):
        facade_smoke._start_daemon_if_needed(BrokenDaemon())


def test_facade_request_through_client_reports_subprocess_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="client failed")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(FacadeSmokeError, match="client failed"):
        _request_through_client(
            socket_path=Path("/tmp/broker.sock"),
            profile="llm",
            session_id="session",
            payload={"id": "one"},
        )


def test_facade_request_through_client_reports_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="not-json", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(FacadeSmokeError, match="invalid client response"):
        _request_through_client(
            socket_path=Path("/tmp/broker.sock"),
            profile="llm",
            session_id="session",
            payload={"id": "one"},
        )


def test_facade_raise_on_error_maps_jsonrpc_error() -> None:
    with pytest.raises(FacadeSmokeError, match='"code": -32000'):
        _raise_on_error({"error": {"code": -32000, "message": "bad upstream"}})


def test_facade_stop_smoke_session_swallows_client_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.facade_smoke as facade_smoke

    calls: list[dict[str, object]] = []

    def successful_request(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"result": {}}

    monkeypatch.setattr(facade_smoke, "_request_through_client", successful_request)
    facade_smoke._stop_smoke_session(Path("/tmp/broker.sock"), "llm", "session-a")
    assert calls[0]["payload"] == {
        "id": "broker/session/stop",
        "method": "broker/session/stop",
        "params": {"broker_session_id": "session-a"},
    }

    def failed_request(**_kwargs: object) -> dict[str, object]:
        raise facade_smoke.FacadeSmokeError("ignored")

    monkeypatch.setattr(facade_smoke, "_request_through_client", failed_request)
    facade_smoke._stop_smoke_session(Path("/tmp/broker.sock"), "llm", "session-b")


def test_facade_run_smoke_stops_session_when_daemon_already_running(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import mcp_broker.facade_smoke as facade_smoke
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig

    config = BrokerConfig(
        runtime=RuntimeConfig(
            root=tmp_path / "runtime",
            socket_path=tmp_path / "broker.sock",
            log_dir=tmp_path / "runtime" / "logs",
            state_dir=tmp_path / "runtime" / "state",
            secrets_dir=tmp_path / "runtime" / "secrets",
        ),
        broker=BrokerSettings(),
        upstreams={},
    )
    stopped: list[tuple[Path, str, str]] = []

    class AlreadyRunningDaemon:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise facade_smoke.BrokerDaemonError("broker daemon already running")

    monkeypatch.setattr(facade_smoke.BrokerConfig, "from_file", lambda _path: config)
    monkeypatch.setattr(facade_smoke, "BrokerDaemon", AlreadyRunningDaemon)
    monkeypatch.setattr(
        facade_smoke,
        "_exercise_client_shim",
        lambda **_kwargs: {
            "tools/list": {"result": {"tools": []}},
            "broker.search_tools": {"result": {"content": [{"type": "text", "text": '{"matches": []}'}]}},
            "broker.describe_tool": {
                "result": {"content": [{"type": "text", "text": '{"tool": {"name": "fake.echo"}}'}]}
            },
            "fake.echo": {"id": "fake.echo", "result": {"content": []}},
        },
    )
    monkeypatch.setattr(
        facade_smoke,
        "_stop_smoke_session",
        lambda socket_path, profile, session_id: stopped.append((socket_path, profile, session_id)),
    )

    report = facade_smoke._run_smoke(
        Namespace(
            config=str(tmp_path / "broker.yaml"),
            profile="llm",
            query="echo",
            call_tool="fake.echo",
            call_args="{}",
        )
    )

    assert report["started_daemon"] is False
    assert stopped[0][0] == tmp_path / "broker.sock"
    assert stopped[0][1] == "llm"


def test_broker_status_reports_profile_upstream_visibility_without_listing_tools() -> None:
    from mcp_broker.catalog import BrokerCatalogFacade
    from mcp_broker.profiles import ToolExposureProfile

    listed_upstreams: list[str] = []
    visible_sets: list[set[str] | None] = []

    def status_health_snapshot(visible_upstreams: set[str] | None) -> dict[str, dict[str, object]]:
        visible_sets.append(visible_upstreams)
        return _status_health_snapshot(visible_upstreams)

    result = BrokerCatalogFacade(
        broker_config=_status_broker_config(),
        profile=ToolExposureProfile(name="llm-profile", max_tools=80, compact_tools_enabled=True),
        list_upstream=lambda name, timeout: listed_upstreams.append(name) or [],
        call_upstream=lambda name, tool, args, timeout: {"content": []},
        call_locks={},
        status_provider=status_health_snapshot,
    ).call_tool("broker.status", {})

    payload = json.loads(result["content"][0]["text"])

    assert listed_upstreams == []
    assert visible_sets == [{"browser-session", "missing-auth", "read-store"}]
    assert payload == _expected_status_payload()


def _status_broker_config():
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig, UpstreamConfig

    return BrokerConfig(
        runtime=RuntimeConfig.from_mapping({"root": "/tmp/mcp-broker-test"}),
        broker=BrokerSettings(),
        upstreams={
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                profiles=("llm-profile",),
                purpose="Memory upstream.",
            ),
            "browser-session": UpstreamConfig(
                name="browser-session",
                command="browser-session",
                mode="per_session",
                profiles=("llm-profile",),
            ),
            "missing-auth": UpstreamConfig(
                name="missing-auth",
                command="missing-auth",
                profiles=("llm-profile",),
            ),
            "disabled": UpstreamConfig(
                name="disabled",
                command="disabled",
                enabled=False,
                profiles=("llm-profile",),
            ),
            "other-profile-only": UpstreamConfig(
                name="other-profile-only",
                command="other-profile-only",
                profiles=("other-profile",),
            ),
        },
    )


def _status_health_snapshot(
    _visible_upstreams: set[str] | None = None,
) -> dict[str, dict[str, object]]:
    return {
        "read-store": {
            "state": "running",
            "pid": 123,
            "restarts": 1,
            "last_error": None,
            "auth_state": "authenticated",
            "auth_repair_attempts": 2,
            "auth_repair_successes": 1,
            "auth_repair_failures": 1,
        },
        "browser-session": {
            "state": "running",
            "pid": None,
            "restarts": 0,
            "last_error": None,
            "sessions": 2,
        },
        "missing-auth": {
            "state": "configured",
            "pid": None,
            "restarts": 0,
            "last_error": "missing environment variable: API_TOKEN required for auth",
        },
        "disabled": {"state": "disabled", "last_error": None},
        "other-profile-only": {"state": "configured", "last_error": None},
    }


def _expected_status_payload() -> dict[str, object]:
    return {
        "profile": "llm-profile",
        "upstreams": {
            "disabled": {
                "enabled": False,
                "auth_probe": "none",
                "auth_repair_attempts": 0,
                "auth_repair_failures": 0,
                "auth_repair_successes": 0,
                "auth_state": "unknown",
                "exposed": False,
                "last_error": None,
                "mode": "shared",
                "mutating": False,
                "pid": None,
                "restarts": None,
                "session_count": 0,
                "state": "disabled",
                "transport": "stdio",
            },
            "missing-auth": {
                "enabled": True,
                "auth_probe": "none",
                "auth_repair_attempts": 0,
                "auth_repair_failures": 0,
                "auth_repair_successes": 0,
                "auth_state": "unauthenticated",
                "exposed": True,
                "last_error": "missing environment variable: API_TOKEN required for auth",
                "mode": "shared",
                "mutating": False,
                "pid": None,
                "restarts": 0,
                "session_count": 0,
                "state": "configured",
                "transport": "stdio",
            },
            "read-store": {
                "enabled": True,
                "auth_probe": "none",
                "auth_repair_attempts": 2,
                "auth_repair_failures": 1,
                "auth_repair_successes": 1,
                "auth_state": "authenticated",
                "exposed": True,
                "last_error": None,
                "mode": "shared",
                "mutating": False,
                "pid": 123,
                "restarts": 1,
                "session_count": 0,
                "state": "running",
                "transport": "stdio",
            },
            "browser-session": {
                "enabled": True,
                "auth_probe": "none",
                "auth_repair_attempts": 0,
                "auth_repair_failures": 0,
                "auth_repair_successes": 0,
                "auth_state": "unknown",
                "exposed": True,
                "last_error": None,
                "mode": "per_session",
                "mutating": False,
                "pid": None,
                "restarts": 0,
                "session_count": 2,
                "state": "running",
                "transport": "stdio",
            },
        },
    }


def test_broker_status_rejects_arguments() -> None:
    from mcp_broker.catalog import BrokerCatalogFacade
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig
    from mcp_broker.profiles import ToolExposureProfile

    facade = BrokerCatalogFacade(
        broker_config=BrokerConfig(
            runtime=RuntimeConfig.from_mapping({"root": "/tmp/mcp-broker-test"}),
            broker=BrokerSettings(),
            upstreams={},
        ),
        profile=ToolExposureProfile(name="llm-profile", max_tools=80, compact_tools_enabled=True),
        list_upstream=lambda name, timeout: [],
        call_upstream=lambda name, tool, args, timeout: {"content": []},
        call_locks={},
    )

    with pytest.raises(ValueError, match="broker.status does not accept arguments"):
        facade.call_tool("broker.status", {"verbose": True})


def test_broker_status_keeps_non_auth_errors_unknown() -> None:
    from mcp_broker.catalog import BrokerCatalogFacade
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig, UpstreamConfig
    from mcp_broker.profiles import ToolExposureProfile

    result = BrokerCatalogFacade(
        broker_config=BrokerConfig(
            runtime=RuntimeConfig.from_mapping({"root": "/tmp/mcp-broker-test"}),
            broker=BrokerSettings(),
            upstreams={
                "display": UpstreamConfig(
                    name="display",
                    command="display",
                    profiles=("llm-profile",),
                )
            },
        ),
        profile=ToolExposureProfile(name="llm-profile", max_tools=80, compact_tools_enabled=True),
        list_upstream=lambda name, timeout: [],
        call_upstream=lambda name, tool, args, timeout: {"content": []},
        call_locks={},
        status_provider=lambda _visible_upstreams: {
            "display": {"last_error": "missing environment variable: DISPLAY"},
        },
    ).call_tool("broker.status", {})

    payload = json.loads(result["content"][0]["text"])

    assert payload["upstreams"]["display"]["auth_state"] == "unknown"
