import json
from argparse import Namespace
from pathlib import Path

import pytest

from mcp_broker.discovery_parity import (
    DiscoveryParityError,
    _client_request,
    _tool_payload,
    build_parity_report,
    compare_profile_discovery,
    run_profile_discovery,
)


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


class SequenceRequester:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses

    def __call__(self, *args, **kwargs) -> dict:
        return self.responses.pop(0)


def test_compare_profile_discovery_accepts_matching_profiles() -> None:
    left = {
        "profile": "codex",
        "advertised_tools": [
            "broker.call_tool",
            "broker.describe_tool",
            "broker.search_tools",
            "broker.status",
        ],
        "visible_upstreams": ["read-store"],
        "search_matches": ["read-store.get_project_scope"],
        "described_tool": "read-store.get_project_scope",
        "call_text": '{"project": "demo"}',
    }
    right = left | {"profile": "claude"}

    assert compare_profile_discovery(left, right) == []


def test_compare_profile_discovery_reports_all_profile_drift() -> None:
    left = {
        "profile": "codex",
        "advertised_tools": ["broker.search_tools"],
        "visible_upstreams": ["read-store"],
        "search_matches": ["read-store.get_project_scope"],
        "described_tool": "read-store.get_project_scope",
        "call_text": '{"project": "demo"}',
    }
    right = {
        "profile": "claude",
        "advertised_tools": ["broker.search_tools", "broker.status"],
        "visible_upstreams": ["read-store", "knowledge-service"],
        "search_matches": ["knowledge.kb_health"],
        "described_tool": "knowledge.kb_health",
        "call_text": '{"status": "ok"}',
    }

    assert compare_profile_discovery(left, right) == [
        "advertised_tools mismatch: codex=['broker.search_tools'] claude=['broker.search_tools', 'broker.status']",
        "visible_upstreams mismatch: codex=['read-store'] claude=['knowledge-service', 'read-store']",
        "search_matches mismatch: codex=['read-store.get_project_scope'] claude=['knowledge.kb_health']",
        "described_tool mismatch: codex='read-store.get_project_scope' claude='knowledge.kb_health'",
        "call_text mismatch: codex='{\"project\": \"demo\"}' claude='{\"status\": \"ok\"}'",
    ]


def test_build_parity_report_indexes_profiles_and_match_state() -> None:
    left = {
        "profile": "codex",
        "advertised_tools": ["broker.search_tools"],
        "visible_upstreams": ["read-store"],
        "search_matches": ["read-store.get_project_scope"],
        "described_tool": "read-store.get_project_scope",
        "call_text": "{}",
    }
    right = left | {"profile": "claude"}

    assert build_parity_report(left=left, right=right, started_daemon=False) == {
        "matches": True,
        "mismatches": [],
        "profiles": {
            "codex": left,
            "claude": right,
        },
        "started_daemon": False,
    }


def test_tool_payload_accepts_text_fallback() -> None:
    assert _tool_payload(
        {
            "result": {
                "content": [{"type": "text", "text": json.dumps({"matches": []})}],
            }
        }
    ) == {"matches": []}


def test_client_request_delegates_to_client_shim() -> None:
    seen = {}

    def local_transport(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return {"result": {"ok": True}}

    assert _client_request(
        Path("/tmp/broker.sock"),
        "codex",
        "session",
        {"id": "one", "method": "tools/list"},
        transport_fn=local_transport,
    ) == {"result": {"ok": True}}
    assert seen == {
        "socket_path": Path("/tmp/broker.sock"),
        "profile": "codex",
        "session_id": "session",
        "payload": {"id": "one", "method": "tools/list"},
    }


def test_run_profile_discovery_rejects_tool_level_error() -> None:
    responses = [
        {"result": {}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": {}}}},
        {"result": {"structuredContent": {"matches": []}}},
        {"result": {"structuredContent": {"tool": {"name": "echo.echo"}}}},
        {"result": {"content": [{"type": "text", "text": "Error: missing"}]}},
    ]

    with pytest.raises(DiscoveryParityError, match="safe call returned upstream error"):
        run_profile_discovery(
            socket_path=Path("/tmp/unused.sock"),
            profile="codex",
            query="echo",
            call_tool="echo.echo",
            call_args={},
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_run_profile_discovery_summarizes_profile_probe() -> None:
    assert run_profile_discovery(
        socket_path=Path("/tmp/unused.sock"),
        profile="codex",
        query="read-store",
        call_tool="read-store.get_project_scope",
        call_args={},
        session_id="session",
        request_fn=SequenceRequester(_profile_probe_responses()),
    ) == {
        "profile": "codex",
        "advertised_tools": ["broker.search_tools", "broker.status"],
        "visible_upstreams": ["read-store"],
        "search_matches": ["read-store.get_project_scope", "read-store.search"],
        "described_tool": "read-store.get_project_scope",
        "call_text": '{"project": "demo"}',
    }


def _profile_probe_responses() -> list[dict]:
    return [
        {"result": {}},
        {"result": {"tools": [{"name": "broker.status"}, {"name": "broker.search_tools"}]}},
        {
            "result": {
                "structuredContent": {
                    "upstreams": {"hidden": {"exposed": False}, "read-store": {"exposed": True}}
                }
            }
        },
        {
            "result": {
                "structuredContent": {
                    "matches": [
                        {"name": "read-store.search"},
                        {"name": "read-store.get_project_scope"},
                    ]
                }
            }
        },
        {"result": {"structuredContent": {"tool": {"name": "read-store.get_project_scope"}}}},
        {"result": {"content": [{"type": "text", "text": '{"project": "demo"}'}]}},
    ]


def test_run_profile_discovery_rejects_invalid_status_payload() -> None:
    responses = [
        {"result": {}},
        {"result": {"tools": [{"name": "broker.search_tools"}]}},
        {"result": {"structuredContent": {"upstreams": []}}},
        {"result": {"structuredContent": {"matches": []}}},
        {"result": {"structuredContent": {"tool": {"name": "echo.echo"}}}},
        {"result": {"content": [{"type": "text", "text": "ok"}]}},
    ]

    with pytest.raises(DiscoveryParityError, match="broker.status returned invalid upstream map"):
        run_profile_discovery(
            socket_path=Path("/tmp/unused.sock"),
            profile="codex",
            query="echo",
            call_tool="echo.echo",
            call_args={},
            session_id="session",
            request_fn=SequenceRequester(responses),
        )


def test_discovery_parity_main_returns_one_for_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import mcp_broker.discovery_parity as discovery_parity

    monkeypatch.setattr(
        discovery_parity,
        "_run_parity",
        lambda _args: {
            "matches": False,
            "mismatches": ["advertised_tools mismatch"],
            "profiles": {},
            "started_daemon": False,
        },
    )

    result = discovery_parity.main(
        [
            "--config",
            "/tmp/broker.yaml",
            "--query",
            "echo",
            "--call-tool",
            "echo.echo",
            "--call-args",
            "{}",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert json.loads(captured.out)["mismatches"] == ["advertised_tools mismatch"]


def test_discovery_parity_main_reports_probe_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import mcp_broker.discovery_parity as discovery_parity

    def raise_error(_args: object) -> dict:
        raise discovery_parity.DiscoveryParityError("bad parity")

    monkeypatch.setattr(discovery_parity, "_run_parity", raise_error)

    result = discovery_parity.main(
        [
            "--config",
            "/tmp/broker.yaml",
            "--query",
            "echo",
            "--call-tool",
            "echo.echo",
            "--call-args",
            "{}",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err == "bad parity\n"


def test_discovery_parity_cleanup_stops_sessions_for_existing_daemon(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import mcp_broker.discovery_parity as discovery_parity
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig

    stopped: list[tuple[Path, str, str]] = []
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
    args = Namespace(left_profile="left", right_profile="right")
    monkeypatch.setattr(
        discovery_parity,
        "_stop_smoke_session",
        lambda socket_path, profile, session_id: stopped.append((socket_path, profile, session_id)),
    )

    discovery_parity._cleanup_parity_daemon(
        config,
        args,
        daemon=object(),
        started_daemon=False,
        left_session_id="left-session",
        right_session_id="right-session",
    )

    assert stopped == [
        (tmp_path / "broker.sock", "left", "left-session"),
        (tmp_path / "broker.sock", "right", "right-session"),
    ]
