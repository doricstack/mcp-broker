import json
from argparse import Namespace
from pathlib import Path
import subprocess
import runpy
import sys

import pytest

from mcp_broker.facade_smoke import (
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    FacadeSmokeError,
    _ConfiguredFacadeProbe,
    _call_payload,
    _cleanup_smoke_daemon,
    _describe_payload,
    _empty_to_none,
    _exercise_client_shim,
    _request_through_client,
    _parse_args,
    _resolve_facade_probe,
    _run_smoke,
    _initialize_payload,
    _search_payload,
    _smoke_request,
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
    assert parse_call_args('{"nested":{"enabled":true},"items":[1,2]}') == {
        "nested": {"enabled": True},
        "items": [1, 2],
    }

    with pytest.raises(ValueError, match="call args must be a JSON object") as exc_info:
        parse_call_args('["bad"]')
    assert str(exc_info.value) == "call args must be a JSON object"


def test_parse_args_keeps_smoke_probe_optional_and_configures_timeout() -> None:
    args = _parse_args(
        [
            "--config",
            "config/broker.example.yaml",
            "--profile",
            "llm-profile",
            "--request-timeout-seconds",
            "9",
        ]
    )

    assert args.config == "config/broker.example.yaml"
    assert args.profile == "llm-profile"
    assert args.query is None
    assert args.call_tool is None
    assert args.call_args is None
    assert args.request_timeout_seconds == 9


def test_parse_args_requires_config_and_preserves_defaults() -> None:
    args = _parse_args(["--config", "config/broker.example.yaml"])

    assert args.config == "config/broker.example.yaml"
    assert args.profile == "codex"
    assert args.query is None
    assert args.call_tool is None
    assert args.call_args is None
    assert args.request_timeout_seconds == DEFAULT_REQUEST_TIMEOUT_SECONDS

    with pytest.raises(SystemExit) as exc_info:
        _parse_args([])
    assert exc_info.value.code == 2


def test_parse_args_help_names_facade_smoke_purpose(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _parse_args(["--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "Exercise compact Codex broker facade" in captured.out
    assert "XX" not in captured.out


def test_resolve_facade_probe_uses_configured_profile_smoke_probe() -> None:
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig, UpstreamConfig
    from mcp_broker.schema import SmokeProbe

    config = BrokerConfig(
        runtime=RuntimeConfig.from_mapping({"root": "/tmp/mcp-broker-test"}),
        broker=BrokerSettings(),
        upstreams={
            "later-store": UpstreamConfig(
                name="later-store",
                command="later-store",
                profiles=("llm-profile",),
                smoke=SmokeProbe(
                    query="later query",
                    tool="later-store.read",
                    arguments={"later": True},
                ),
            ),
            "first-store": UpstreamConfig(
                name="first-store",
                command="first-store",
                profiles=("llm-profile",),
                smoke=SmokeProbe(
                    query="first query",
                    tool="first-store.read",
                    arguments={"first": True},
                ),
            ),
            "other-profile": UpstreamConfig(
                name="other-profile",
                command="other-profile",
                profiles=("other-profile",),
                smoke=SmokeProbe(query="other query", tool="other.read", arguments={}),
            ),
            "disabled-store": UpstreamConfig(
                name="disabled-store",
                command="disabled-store",
                enabled=False,
                profiles=("llm-profile",),
                smoke=SmokeProbe(query="disabled query", tool="disabled.read", arguments={}),
            ),
            "describe-only": UpstreamConfig(
                name="describe-only",
                command="describe-only",
                profiles=("llm-profile",),
                smoke=SmokeProbe(
                    query="describe query",
                    tool="describe-only.read",
                    arguments={},
                    call=False,
                ),
            ),
        },
    )

    assert _resolve_facade_probe(
        config=config,
        profile="llm-profile",
        query=None,
        call_tool=None,
        call_args=None,
    ) == _ConfiguredFacadeProbe(
        query="first query",
        call_tool="first-store.read",
        call_args={"first": True},
    )


def test_resolve_facade_probe_rejects_partial_explicit_probe() -> None:
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig

    config = BrokerConfig(
        runtime=RuntimeConfig.from_mapping({"root": "/tmp/mcp-broker-test"}),
        broker=BrokerSettings(),
        upstreams={},
    )

    with pytest.raises(FacadeSmokeError, match="provide query, call-tool, and call-args") as exc_info:
        _resolve_facade_probe(
            config=config,
            profile="llm-profile",
            query="repo",
            call_tool="fake.echo",
            call_args=None,
        )
    assert str(exc_info.value) == (
        "provide query, call-tool, and call-args together or omit all to use YAML smoke"
    )


def test_resolve_facade_probe_uses_explicit_probe_without_config_inventory() -> None:
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig

    config = BrokerConfig(
        runtime=RuntimeConfig.from_mapping({"root": "/tmp/mcp-broker-test"}),
        broker=BrokerSettings(),
        upstreams={},
    )

    assert _resolve_facade_probe(
        config=config,
        profile="llm-profile",
        query="explicit query",
        call_tool="generic.echo",
        call_args='{"value":"ok"}',
    ) == _ConfiguredFacadeProbe(
        query="explicit query",
        call_tool="generic.echo",
        call_args={"value": "ok"},
    )


def test_resolve_facade_probe_rejects_profiles_without_callable_smoke_probe() -> None:
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig, UpstreamConfig
    from mcp_broker.schema import SmokeProbe

    config = BrokerConfig(
        runtime=RuntimeConfig.from_mapping({"root": "/tmp/mcp-broker-test"}),
        broker=BrokerSettings(),
        upstreams={
            "describe-only": UpstreamConfig(
                name="describe-only",
                command="describe-only",
                profiles=("llm-profile",),
                smoke=SmokeProbe(
                    query="describe query",
                    tool="describe-only.read",
                    arguments={},
                    call=False,
                ),
            ),
            "disabled-mode": UpstreamConfig(
                name="disabled-mode",
                command="disabled-mode",
                mode="disabled",
                profiles=("llm-profile",),
                smoke=SmokeProbe(query="disabled query", tool="disabled.read", arguments={}),
            )
        },
    )

    with pytest.raises(FacadeSmokeError, match="llm-profile has no callable smoke probe"):
        _resolve_facade_probe(
            config=config,
            profile="llm-profile",
            query=None,
            call_tool=None,
            call_args=None,
        )


def test_resolve_facade_probe_rejects_callable_smoke_for_other_profile() -> None:
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig, UpstreamConfig
    from mcp_broker.schema import SmokeProbe

    config = BrokerConfig(
        runtime=RuntimeConfig.from_mapping({"root": "/tmp/mcp-broker-test"}),
        broker=BrokerSettings(),
        upstreams={
            "other-profile": UpstreamConfig(
                name="other-profile",
                command="other-profile",
                profiles=("other-profile",),
                smoke=SmokeProbe(query="other query", tool="other.read", arguments={}),
            ),
        },
    )

    with pytest.raises(FacadeSmokeError) as exc_info:
        _resolve_facade_probe(
            config=config,
            profile="llm-profile",
            query=None,
            call_tool=None,
            call_args=None,
        )

    assert str(exc_info.value) == "llm-profile has no callable smoke probe"


def test_empty_to_none_only_normalizes_missing_explicit_values() -> None:
    assert _empty_to_none(None) is None
    assert _empty_to_none("") is None
    assert _empty_to_none(" ") == " "
    assert _empty_to_none("query") == "query"


def test_facade_payload_helpers_build_expected_jsonrpc_messages() -> None:
    assert _initialize_payload() == {
        "jsonrpc": "2.0",
        "id": "initialize",
        "method": "initialize",
        "params": {"protocolVersion": "2025-11-25"},
    }
    assert _tools_list_payload() == {
        "jsonrpc": "2.0",
        "id": "tools/list",
        "method": "tools/list",
    }
    assert _search_payload("read-store") == {
        "jsonrpc": "2.0",
        "id": "broker.search_tools",
        "method": "tools/call",
        "params": {
            "name": "broker.search_tools",
            "arguments": {"query": "read-store", "limit": 10},
        },
    }
    assert _describe_payload("read-store.get_project_scope") == {
        "jsonrpc": "2.0",
        "id": "broker.describe_tool",
        "method": "tools/call",
        "params": {
            "name": "broker.describe_tool",
            "arguments": {"name": "read-store.get_project_scope"},
        },
    }
    assert _call_payload("read-store.get_project_scope", {"scope": "project"}) == {
        "jsonrpc": "2.0",
        "id": "read-store.get_project_scope",
        "method": "tools/call",
        "params": {
            "name": "broker.call_tool",
            "arguments": {
                "name": "read-store.get_project_scope",
                "arguments": {"scope": "project"},
            },
        },
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


def test_build_facade_smoke_report_rejects_jsonrpc_tool_errors() -> None:
    with pytest.raises(FacadeSmokeError, match="generic.echo returned upstream error"):
        build_facade_smoke_report(
            profile="llm-profile",
            list_response={"result": {"tools": [{"name": "broker.call_tool"}]}},
            search_response={
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps({"matches": [{"name": "generic.echo"}]})}
                    ]
                }
            },
            describe_response={
                "result": {
                    "content": [
                        {"type": "text", "text": json.dumps({"tool": {"name": "generic.echo"}})}
                    ]
                }
            },
            call_response={
                "id": "generic.echo",
                "result": {"content": [], "isError": True},
            },
            started_daemon=False,
        )


def test_build_facade_smoke_report_preserves_empty_call_text() -> None:
    report = build_facade_smoke_report(
        profile="llm-profile",
        list_response={"result": {"tools": [{"name": "broker.call_tool"}]}},
        search_response={
            "result": {"content": [{"type": "text", "text": json.dumps({"matches": []})}]}
        },
        describe_response={
            "result": {"content": [{"type": "text", "text": json.dumps({"tool": {"name": "fake.echo"}})}]}
        },
        call_response={"id": "fake.echo", "result": {"content": []}},
        started_daemon=False,
    )

    assert report["call_text"] == ""


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
    assert captured.err == "call args must be a JSON object\n"


def test_facade_smoke_main_passes_parsed_args_to_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import mcp_broker.facade_smoke as facade_smoke

    observed: dict[str, object] = {}

    def fake_run_smoke(args: Namespace) -> dict[str, object]:
        observed["args"] = args
        return {"ok": True}

    monkeypatch.setattr(facade_smoke, "_run_smoke", fake_run_smoke)

    result = facade_smoke.main(["--config", "broker.yaml", "--profile", "llm"])

    captured = capsys.readouterr()
    args = observed["args"]
    assert result == 0
    assert args.config == "broker.yaml"
    assert args.profile == "llm"
    assert captured.out == '{"ok": true}\n'


def test_facade_smoke_main_writes_sorted_json_on_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import mcp_broker.facade_smoke as facade_smoke

    monkeypatch.setattr(
        facade_smoke,
        "_run_smoke",
        lambda _args: {"zeta": 1, "alpha": 2},
    )

    result = facade_smoke.main(["--config", "config/broker.example.yaml"])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out == '{"alpha": 2, "zeta": 1}\n'


def test_facade_start_daemon_accepts_existing_daemon() -> None:
    import mcp_broker.facade_smoke as facade_smoke

    class AlreadyRunningDaemon:
        def start(self) -> None:
            raise facade_smoke.BrokerDaemonError("broker daemon already running")

    assert facade_smoke._start_daemon_if_needed(AlreadyRunningDaemon()) is False


def test_facade_start_daemon_returns_true_after_starting_new_daemon() -> None:
    import mcp_broker.facade_smoke as facade_smoke

    class NewDaemon:
        def __init__(self) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

    daemon = NewDaemon()

    assert facade_smoke._start_daemon_if_needed(daemon) is True
    assert daemon.started is True


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


def test_facade_request_through_client_uses_default_failure_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(FacadeSmokeError) as exc_info:
        _request_through_client(
            socket_path=Path("/tmp/broker.sock"),
            profile="llm",
            session_id="session",
            payload={"id": "one"},
        )

    assert str(exc_info.value) == "client shim failed"


def test_facade_request_through_client_sends_exact_client_command_and_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["args"] = args
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"result":{"ok":true}}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    payload = {"jsonrpc": "2.0", "id": "request-id", "method": "tools/list"}
    response = _request_through_client(
        socket_path=tmp_path / "broker.sock",
        profile="llm-profile",
        session_id="session-1",
        payload=payload,
        timeout_seconds=11,
    )

    assert response == {"result": {"ok": True}}
    command = observed["args"][0]
    assert command == [
        subprocess.sys.executable,
        "-m",
        "mcp_broker.client",
        "--socket-path",
        str(tmp_path / "broker.sock"),
        "--profile",
        "llm-profile",
        "--session-id",
        "session-1",
    ]
    assert observed["kwargs"]["input"] == json.dumps(payload) + "\n"
    assert observed["kwargs"]["timeout"] == 11
    assert observed["kwargs"]["text"] is True
    assert observed["kwargs"]["check"] is False
    assert observed["kwargs"]["stdout"] == subprocess.PIPE
    assert observed["kwargs"]["stderr"] == subprocess.PIPE


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


def test_facade_request_through_client_reports_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(FacadeSmokeError) as exc_info:
        _request_through_client(
            socket_path=Path("/tmp/broker.sock"),
            profile="llm",
            session_id="session",
            payload={"id": "one"},
            timeout_seconds=3,
        )
    assert str(exc_info.value) == "client shim timed out after 3s for one"

    with pytest.raises(FacadeSmokeError) as fallback_exc:
        _request_through_client(
            socket_path=Path("/tmp/broker.sock"),
            profile="llm",
            session_id="session",
            payload={},
            timeout_seconds=3,
        )
    assert str(fallback_exc.value) == "client shim timed out after 3s for request"


def test_facade_raise_on_error_maps_jsonrpc_error() -> None:
    with pytest.raises(FacadeSmokeError) as exc_info:
        _raise_on_error({"error": {"message": "bad upstream", "code": -32000}})
    assert str(exc_info.value) == '{"code": -32000, "message": "bad upstream"}'


def test_facade_smoke_request_passes_timeout_to_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import mcp_broker.facade_smoke as facade_smoke

    observed: dict[str, object] = {}

    def fake_request(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {"result": {}}

    monkeypatch.setattr(facade_smoke, "_request_through_client", fake_request)

    assert facade_smoke._smoke_request(
        tmp_path / "broker.sock",
        "llm-profile",
        "session-1",
        {"id": "request-id"},
        timeout_seconds=17,
    ) == {"result": {}}
    assert observed["timeout_seconds"] == 17
    assert observed["socket_path"] == tmp_path / "broker.sock"
    assert observed["profile"] == "llm-profile"
    assert observed["session_id"] == "session-1"
    assert observed["payload"] == {"id": "request-id"}


def test_facade_exercise_client_shim_sends_requests_in_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import mcp_broker.facade_smoke as facade_smoke

    calls: list[dict[str, object]] = []

    def fake_smoke_request(
        socket_path: Path,
        profile: str,
        session_id: str,
        payload: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> dict[str, object]:
        calls.append(
            {
                "socket_path": socket_path,
                "profile": profile,
                "session_id": session_id,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return {"id": payload["id"], "result": {"content": []}}

    monkeypatch.setattr(facade_smoke, "_smoke_request", fake_smoke_request)

    responses = facade_smoke._exercise_client_shim(
        socket_path=tmp_path / "broker.sock",
        profile="llm-profile",
        query="read-store",
        call_tool="read-store.fetch",
        call_args={"id": "abc"},
        session_id="session-1",
        timeout_seconds=23,
    )

    assert [call["payload"]["id"] for call in calls] == [
        "initialize",
        "tools/list",
        "broker.search_tools",
        "broker.describe_tool",
        "read-store.fetch",
    ]
    assert [call["payload"] for call in calls] == [
        facade_smoke._initialize_payload(),
        facade_smoke._tools_list_payload(),
        facade_smoke._search_payload("read-store"),
        facade_smoke._describe_payload("read-store.fetch"),
        facade_smoke._call_payload("read-store.fetch", {"id": "abc"}),
    ]
    assert {call["socket_path"] for call in calls} == {tmp_path / "broker.sock"}
    assert {call["profile"] for call in calls} == {"llm-profile"}
    assert {call["session_id"] for call in calls} == {"session-1"}
    assert {call["timeout_seconds"] for call in calls} == {23}
    assert responses == {
        "tools/list": {"id": "tools/list", "result": {"content": []}},
        "broker.search_tools": {"id": "broker.search_tools", "result": {"content": []}},
        "broker.describe_tool": {"id": "broker.describe_tool", "result": {"content": []}},
        "read-store.fetch": {"id": "read-store.fetch", "result": {"content": []}},
    }


def test_facade_exercise_client_shim_stops_on_first_jsonrpc_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import mcp_broker.facade_smoke as facade_smoke

    calls: list[str] = []

    def fake_smoke_request(
        _socket_path: Path,
        _profile: str,
        _session_id: str,
        payload: dict[str, object],
        *,
        timeout_seconds: int,
    ) -> dict[str, object]:
        calls.append(str(payload["id"]))
        if payload["id"] == "tools/list":
            return {"error": {"code": -32001, "message": "list failed"}}
        return {"id": payload["id"], "result": {"content": []}}

    monkeypatch.setattr(facade_smoke, "_smoke_request", fake_smoke_request)

    with pytest.raises(FacadeSmokeError, match="list failed"):
        facade_smoke._exercise_client_shim(
            socket_path=tmp_path / "broker.sock",
            profile="llm-profile",
            query="read-store",
            call_tool="read-store.fetch",
            call_args={},
            session_id="session-1",
            timeout_seconds=23,
        )

    assert calls == ["initialize", "tools/list"]


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
    assert calls[0]["socket_path"] == Path("/tmp/broker.sock")
    assert calls[0]["profile"] == "llm"
    assert calls[0]["session_id"] == "session-a"
    assert calls[0]["payload"] == {
        "id": "broker/session/stop",
        "method": "broker/session/stop",
        "params": {"broker_session_id": "session-a"},
    }

    def failed_request(**_kwargs: object) -> dict[str, object]:
        raise facade_smoke.FacadeSmokeError("ignored")

    monkeypatch.setattr(facade_smoke, "_request_through_client", failed_request)
    facade_smoke._stop_smoke_session(Path("/tmp/broker.sock"), "llm", "session-b")


def test_facade_cleanup_smoke_daemon_stops_session_when_reusing_daemon(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import mcp_broker.facade_smoke as facade_smoke

    stopped_sessions: list[tuple[Path, str, str]] = []

    class Daemon:
        def join(self, timeout: int) -> None:
            raise AssertionError("join should not run for reused daemon")

        def stop(self) -> None:
            raise AssertionError("stop should not run for reused daemon")

    monkeypatch.setattr(
        facade_smoke,
        "_stop_smoke_session",
        lambda socket_path, profile, session_id: stopped_sessions.append(
            (socket_path, profile, session_id)
        ),
    )

    facade_smoke._cleanup_smoke_daemon(
        tmp_path / "broker.sock",
        "llm-profile",
        "session-1",
        Daemon(),
        started_daemon=False,
    )

    assert stopped_sessions == [(tmp_path / "broker.sock", "llm-profile", "session-1")]


def test_facade_cleanup_smoke_daemon_requests_stop_and_always_stops_daemon(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import mcp_broker.facade_smoke as facade_smoke

    events: list[object] = []

    class Daemon:
        def join(self, timeout: int) -> None:
            events.append(("join", timeout))

        def stop(self) -> None:
            events.append("stop")

    def fake_request(**kwargs: object) -> dict[str, object]:
        events.append(kwargs)
        return {"result": {}}

    monkeypatch.setattr(facade_smoke, "_request_through_client", fake_request)

    facade_smoke._cleanup_smoke_daemon(
        tmp_path / "broker.sock",
        "llm-profile",
        "session-1",
        Daemon(),
        started_daemon=True,
    )

    request = events[0]
    assert request["socket_path"] == tmp_path / "broker.sock"
    assert request["profile"] == "llm-profile"
    assert request["session_id"] == "facade-smoke-stop"
    assert request["payload"] == {"jsonrpc": "2.0", "id": "stop", "method": "broker/stop"}
    assert events[1:] == [("join", 5), "stop"]


def test_facade_cleanup_smoke_daemon_stops_daemon_after_stop_request_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import mcp_broker.facade_smoke as facade_smoke

    events: list[str] = []

    class Daemon:
        def join(self, timeout: int) -> None:
            events.append("join")

        def stop(self) -> None:
            events.append("stop")

    def failed_request(**_kwargs: object) -> dict[str, object]:
        raise FacadeSmokeError("stop failed")

    monkeypatch.setattr(facade_smoke, "_request_through_client", failed_request)

    with pytest.raises(FacadeSmokeError, match="stop failed"):
        facade_smoke._cleanup_smoke_daemon(
            tmp_path / "broker.sock",
            "llm-profile",
            "session-1",
            Daemon(),
            started_daemon=True,
        )

    assert events == ["stop"]


def test_facade_module_entrypoint_runs_arg_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    import mcp_broker.facade_smoke as facade_smoke

    monkeypatch.setattr(sys, "argv", ["facade_smoke.py"])

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(Path(facade_smoke.__file__)), run_name="__main__")

    assert exc_info.value.code == 2


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
            request_timeout_seconds=70,
        )
    )

    assert report["started_daemon"] is False
    assert report["profile"] == "llm"
    assert stopped[0][0] == tmp_path / "broker.sock"
    assert stopped[0][1] == "llm"


def test_facade_run_smoke_wires_config_daemon_probe_and_cleanup(
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
    events: list[tuple[str, object]] = []

    class NewDaemon:
        def __init__(self, **kwargs: object) -> None:
            events.append(("daemon-init", kwargs))

        def start(self) -> None:
            events.append(("daemon-start", None))

    class FixedUuid:
        hex = "abc123"

    def fake_exercise(**kwargs: object) -> dict[str, dict[str, object]]:
        events.append(("exercise", kwargs))
        return {
            "tools/list": {"result": {"tools": []}},
            "broker.search_tools": {"result": {"content": [{"type": "text", "text": '{"matches": []}'}]}},
            "broker.describe_tool": {
                "result": {"content": [{"type": "text", "text": '{"tool": {"name": "fake.echo"}}'}]}
            },
            "fake.echo": {"id": "fake.echo", "result": {"content": []}},
        }

    def fake_cleanup(*args: object, **kwargs: object) -> None:
        events.append(("cleanup", (args, kwargs)))

    monkeypatch.setattr(facade_smoke.BrokerConfig, "from_file", lambda path: events.append(("config", path)) or config)
    monkeypatch.setattr(facade_smoke, "BrokerDaemon", NewDaemon)
    monkeypatch.setattr(facade_smoke, "uuid4", lambda: FixedUuid())
    monkeypatch.setattr(facade_smoke, "_exercise_client_shim", fake_exercise)
    monkeypatch.setattr(facade_smoke, "_cleanup_smoke_daemon", fake_cleanup)

    report = _run_smoke(
        Namespace(
            config=str(tmp_path / "broker.yaml"),
            profile="llm",
            query="echo",
            call_tool="fake.echo",
            call_args='{"value": true}',
            request_timeout_seconds=31,
        )
    )

    assert report["started_daemon"] is True
    assert report["profile"] == "llm"
    assert events[0] == ("config", Path(tmp_path / "broker.yaml"))
    assert events[1] == (
        "daemon-init",
        {
            "runtime_root": tmp_path / "runtime",
            "socket_path": tmp_path / "broker.sock",
            "broker_config": config,
        },
    )
    assert events[3] == (
        "exercise",
        {
            "socket_path": tmp_path / "broker.sock",
            "profile": "llm",
            "query": "echo",
            "call_tool": "fake.echo",
            "call_args": {"value": True},
            "session_id": "facade-smoke-abc123",
            "timeout_seconds": 31,
        },
    )
    cleanup_args, cleanup_kwargs = events[4][1]
    assert cleanup_args[:3] == (
        tmp_path / "broker.sock",
        "llm",
        "facade-smoke-abc123",
    )
    assert cleanup_args[3] is not None
    assert cleanup_kwargs == {"started_daemon": True}


def test_facade_run_smoke_passes_config_and_profile_to_probe_resolver(
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
    observed: dict[str, object] = {}

    class Daemon:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

    def fake_resolve(**kwargs: object) -> _ConfiguredFacadeProbe:
        observed["resolve"] = kwargs
        return _ConfiguredFacadeProbe(
            query="resolved query",
            call_tool="resolved.echo",
            call_args={"value": True},
        )

    def fake_exercise(**kwargs: object) -> dict[str, dict[str, object]]:
        observed["exercise"] = kwargs
        return {
            "tools/list": {"result": {"tools": []}},
            "broker.search_tools": {"result": {"content": [{"type": "text", "text": '{"matches": []}'}]}},
            "broker.describe_tool": {
                "result": {"content": [{"type": "text", "text": '{"tool": {"name": "resolved.echo"}}'}]}
            },
            "resolved.echo": {"id": "resolved.echo", "result": {"content": []}},
        }

    monkeypatch.setattr(facade_smoke.BrokerConfig, "from_file", lambda _path: config)
    monkeypatch.setattr(facade_smoke, "BrokerDaemon", Daemon)
    monkeypatch.setattr(facade_smoke, "_resolve_facade_probe", fake_resolve)
    monkeypatch.setattr(facade_smoke, "_exercise_client_shim", fake_exercise)
    monkeypatch.setattr(facade_smoke, "_cleanup_smoke_daemon", lambda *_args, **_kwargs: None)

    report = _run_smoke(
        Namespace(
            config=str(tmp_path / "broker.yaml"),
            profile="llm",
            query="cli query",
            call_tool="cli.echo",
            call_args='{"cli": true}',
            request_timeout_seconds=44,
        )
    )

    assert observed["resolve"] == {
        "config": config,
        "profile": "llm",
        "query": "cli query",
        "call_tool": "cli.echo",
        "call_args": '{"cli": true}',
    }
    assert observed["exercise"]["query"] == "resolved query"
    assert observed["exercise"]["call_tool"] == "resolved.echo"
    assert observed["exercise"]["call_args"] == {"value": True}
    assert report["called_tool"] == "resolved.echo"


def test_facade_run_smoke_cleans_up_as_reused_daemon_when_start_fails(
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
    cleanup: dict[str, object] = {}

    class Daemon:
        def __init__(self, **_kwargs: object) -> None:
            pass

    def fail_start(_daemon: object) -> bool:
        raise FacadeSmokeError("start failed")

    def fake_cleanup(*args: object, **kwargs: object) -> None:
        cleanup["args"] = args
        cleanup["kwargs"] = kwargs

    monkeypatch.setattr(facade_smoke.BrokerConfig, "from_file", lambda _path: config)
    monkeypatch.setattr(facade_smoke, "BrokerDaemon", Daemon)
    monkeypatch.setattr(
        facade_smoke,
        "_resolve_facade_probe",
        lambda **_kwargs: _ConfiguredFacadeProbe("query", "fake.echo", {}),
    )
    monkeypatch.setattr(facade_smoke, "_start_daemon_if_needed", fail_start)
    monkeypatch.setattr(facade_smoke, "_cleanup_smoke_daemon", fake_cleanup)

    with pytest.raises(FacadeSmokeError, match="start failed"):
        _run_smoke(
            Namespace(
                config=str(tmp_path / "broker.yaml"),
                profile="llm",
                query="echo",
                call_tool="fake.echo",
                call_args="{}",
                request_timeout_seconds=31,
            )
        )

    cleanup_args = cleanup["args"]
    assert cleanup_args[:3] == (tmp_path / "broker.sock", "llm", cleanup_args[2])
    assert cleanup["kwargs"] == {"started_daemon": False}


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


def test_broker_facade_accepts_canonical_names_without_profile() -> None:
    from mcp_broker.broker import BrokerToolError
    from mcp_broker.catalog import BrokerCatalogFacade

    facade = BrokerCatalogFacade(
        broker_config=_status_broker_config(),
        profile=None,
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    )

    with pytest.raises(BrokerToolError, match="unknown broker tool: broker.unknown"):
        facade.call_tool("broker.unknown", {})


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


def test_broker_status_ignores_client_control_arguments() -> None:
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

    result = facade.call_tool("broker.status", {"wait_for_previous": True})

    payload = json.loads(result["content"][0]["text"])
    assert payload["profile"] == "llm-profile"


def test_broker_status_rejects_status_arguments() -> None:
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
