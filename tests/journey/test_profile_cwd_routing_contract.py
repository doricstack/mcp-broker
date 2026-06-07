from pathlib import Path

import pytest

from mcp_broker.config import (
    BrokerConfig,
    BrokerSettings,
    RuntimeConfig,
    UpstreamConfig,
)
from mcp_broker.daemon import BrokerDaemon
from mcp_broker.profiles import ClientRootMatch, ToolExposureProfile


pytestmark = pytest.mark.journey


def _build(tmp_path: Path, *, compact: bool) -> tuple[BrokerConfig, Path]:
    apps = tmp_path / "Projects" / "apps"
    (apps / "genai-quiz-pro" / "backend").mkdir(parents=True)
    (apps / "genai-quiz-pro-android").mkdir(parents=True)
    (apps / "forte").mkdir(parents=True)
    config = BrokerConfig(
        runtime=RuntimeConfig(
            root=tmp_path / "runtime",
            socket_path=tmp_path / "broker.sock",
            log_dir=tmp_path / "runtime" / "logs",
            state_dir=tmp_path / "runtime" / "state",
            secrets_dir=tmp_path / "runtime" / "secrets",
        ),
        broker=BrokerSettings(),
        profiles={
            "claude": ToolExposureProfile(
                name="claude", max_tools=50, compact_tools_enabled=compact
            ),
            "bfai": ToolExposureProfile(
                name="bfai",
                max_tools=50,
                compact_tools_enabled=compact,
                allow_mutating_upstreams=("bfai-writer",),
                client_root_match=ClientRootMatch(parent=apps, name_prefix="genai-quiz-pro"),
            ),
        },
        upstreams={
            "general": UpstreamConfig(
                name="general",
                command="general",
                mode="shared",
                enabled=True,
                tool_prefix="general",
                profiles=("claude", "bfai"),
            ),
            "bfai-writer": UpstreamConfig(
                name="bfai-writer",
                command="bfai-writer",
                mode="per_session",
                enabled=True,
                tool_prefix="bfai-writer",
                profiles=("bfai",),
                mutating=True,
            ),
        },
    )
    return config, apps


def _daemon_with_list_stub(config: BrokerConfig) -> tuple[BrokerDaemon, list[str]]:
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    listed: list[str] = []

    def record_list(
        upstream_name: str,
        timeout_seconds: int,
        *,
        session_id: str | None = None,
        session_context: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        listed.append(upstream_name)
        return [{"name": "do"}]

    daemon._list_upstream = record_list
    daemon._protocol._initialize_seen = True
    return daemon, listed


def _list(daemon: BrokerDaemon, cwd: str | None) -> dict[str, object] | None:
    params: dict[str, object] = {"profile": "claude"}
    if cwd is not None:
        params["broker_client_cwd"] = cwd
    return daemon._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": "l", "method": "tools/list", "params": params}
    )


def test_genai_cwd_routes_claude_request_to_bfai_and_exposes_bfai_only_upstream(
    tmp_path: Path,
) -> None:
    config, apps = _build(tmp_path, compact=False)
    daemon, listed = _daemon_with_list_stub(config)

    _list(daemon, str(apps / "genai-quiz-pro" / "backend"))

    assert "bfai-writer" in listed
    assert "general" in listed


def test_sibling_genai_cwd_also_routes_to_bfai(tmp_path: Path) -> None:
    config, apps = _build(tmp_path, compact=False)
    daemon, listed = _daemon_with_list_stub(config)

    _list(daemon, str(apps / "genai-quiz-pro-android"))

    assert "bfai-writer" in listed


def test_non_genai_cwd_keeps_claude_and_hides_bfai_only_upstream(tmp_path: Path) -> None:
    config, apps = _build(tmp_path, compact=False)
    daemon, listed = _daemon_with_list_stub(config)

    _list(daemon, str(apps / "forte"))

    assert "bfai-writer" not in listed
    assert "general" in listed


def test_absent_cwd_keeps_claude_and_hides_bfai_only_upstream(tmp_path: Path) -> None:
    config, _apps = _build(tmp_path, compact=False)
    daemon, listed = _daemon_with_list_stub(config)

    _list(daemon, None)

    assert "bfai-writer" not in listed
    assert "general" in listed


def _call_bfai_writer(config: BrokerConfig, cwd: str | None) -> dict[str, object] | None:
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    daemon._protocol._initialize_seen = True

    def call_upstream(
        upstream_name: str, tool_name: str, arguments: dict[str, object], timeout_seconds: int
    ) -> dict[str, object]:
        return {"content": [{"type": "text", "text": f"called {upstream_name}.{tool_name}"}]}

    daemon._call_upstream_for_session = lambda session_id, session_context: call_upstream
    params: dict[str, object] = {
        "profile": "claude",
        "name": "bfai-writer.do",
        "arguments": {},
    }
    if cwd is not None:
        params["broker_client_cwd"] = cwd
    return daemon._handle_jsonrpc_request(
        {"jsonrpc": "2.0", "id": "c", "method": "tools/call", "params": params}
    )


def test_call_path_allows_bfai_tool_from_genai_cwd(tmp_path: Path) -> None:
    config, apps = _build(tmp_path, compact=False)

    response = _call_bfai_writer(config, str(apps / "genai-quiz-pro"))

    assert response is not None
    assert "result" in response
    assert "called bfai-writer.do" in str(response["result"])


def test_call_path_rejects_bfai_tool_from_non_genai_cwd(tmp_path: Path) -> None:
    config, apps = _build(tmp_path, compact=False)

    response = _call_bfai_writer(config, str(apps / "forte"))

    assert response is not None
    assert "error" in response


def test_compact_facade_status_exposes_bfai_only_by_cwd(tmp_path: Path) -> None:
    config, apps = _build(tmp_path, compact=True)
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    daemon._protocol._initialize_seen = True

    def status_call(cwd: str) -> dict[str, object] | None:
        return daemon._handle_jsonrpc_request(
            {
                "jsonrpc": "2.0",
                "id": "s",
                "method": "tools/call",
                "params": {
                    "profile": "claude",
                    "name": "broker.status",
                    "arguments": {},
                    "broker_client_cwd": cwd,
                },
            }
        )

    genai = str(status_call(str(apps / "genai-quiz-pro")))
    forte = str(status_call(str(apps / "forte")))

    assert "bfai-writer" in genai
    assert "bfai-writer" not in forte
