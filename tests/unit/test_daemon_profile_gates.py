from pathlib import Path

import pytest

from mcp_broker.config import BrokerConfig


pytestmark = pytest.mark.unit


def test_daemon_tools_list_applies_profile_before_listing_protected_upstreams(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import BrokerSettings, RuntimeConfig, UpstreamConfig
    from mcp_broker.daemon import BrokerDaemon
    from mcp_broker.profiles import ToolExposureProfile

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
            "llm": ToolExposureProfile(name="llm", max_tools=10),
            "protected": ToolExposureProfile(
                name="protected",
                max_tools=10,
                allow_mutating_upstreams=("workspace-writer",),
            ),
        },
        upstreams={
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                mode="shared",
                enabled=True,
                tool_prefix="read-store",
                profiles=("llm",),
            ),
            "workspace-writer": UpstreamConfig(
                name="workspace-writer",
                command="gws",
                args=["mcp"],
                mode="per_session",
                enabled=True,
                tool_prefix="workspace-writer",
                profiles=("protected",),
                mutating=True,
            ),
        },
    )
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    listed_upstreams: list[str] = []

    def record_list(
        upstream_name: str,
        timeout_seconds: int,
        *,
        session_id: str | None = None,
        session_context: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        assert session_id is None
        assert session_context == {}
        listed_upstreams.append(upstream_name)
        return [{"name": "search"}]

    daemon._list_upstream = record_list
    daemon._protocol._initialize_seen = True

    response = daemon._handle_jsonrpc_request(
        {
            "jsonrpc": "2.0",
            "id": "list-llm",
            "method": "tools/list",
            "params": {"profile": "llm"},
        }
    )

    assert listed_upstreams == ["read-store"]
    assert response["result"] == {"tools": [{"name": "read-store.search"}]}


def test_daemon_tools_list_rejects_invalid_profile_params(tmp_path: Path) -> None:
    from mcp_broker.daemon import BrokerDaemon
    from mcp_broker.jsonrpc import JsonRpcRequest

    config = _empty_config(tmp_path)
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )

    bad_type = daemon._handle_tools_list(
        JsonRpcRequest(
            method="tools/list",
            id="bad-profile-type",
            params={"profile": 123},
            has_id=True,
        )
    )

    assert bad_type.error == {"code": -32602, "message": "profile must be a string"}


def test_daemon_tools_list_rejects_mutating_profile_without_allowlist_before_listing(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import BrokerSettings, RuntimeConfig, UpstreamConfig
    from mcp_broker.daemon import BrokerDaemon
    from mcp_broker.jsonrpc import JsonRpcRequest
    from mcp_broker.profiles import ToolExposureProfile

    config = BrokerConfig(
        runtime=RuntimeConfig(
            root=tmp_path / "runtime",
            socket_path=tmp_path / "broker.sock",
            log_dir=tmp_path / "runtime" / "logs",
            state_dir=tmp_path / "runtime" / "state",
            secrets_dir=tmp_path / "runtime" / "secrets",
        ),
        broker=BrokerSettings(),
        profiles={"protected": ToolExposureProfile(name="protected", max_tools=10)},
        upstreams={
            "workspace-writer": UpstreamConfig(
                name="workspace-writer",
                command="gws",
                args=["mcp"],
                mode="per_session",
                enabled=True,
                tool_prefix="workspace-writer",
                profiles=("protected",),
                mutating=False,
            )
        },
    )
    config.upstreams["workspace-writer"] = UpstreamConfig(
        name="workspace-writer",
        command="gws",
        args=["mcp"],
        mode="per_session",
        enabled=True,
        tool_prefix="workspace-writer",
        profiles=("protected",),
        mutating=True,
    )
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    listed_upstreams: list[str] = []

    def record_list(
        upstream_name: str,
        timeout_seconds: int,
        *,
        session_id: str | None = None,
        session_context: dict[str, str] | None = None,
    ) -> list[dict[str, object]]:
        assert session_id is None
        assert session_context == {}
        listed_upstreams.append(upstream_name)
        return [{"name": "search"}]

    daemon._list_upstream = record_list

    response = daemon._handle_tools_list(
        JsonRpcRequest(
            method="tools/list",
            id="mutating-profile",
            params={"profile": "protected"},
            has_id=True,
        )
    )

    assert response.error == {
        "code": -32000,
        "message": "mutating upstream not allowed for profile: workspace-writer",
    }
    assert listed_upstreams == []


def test_daemon_tools_call_applies_profile_from_params_without_starting_denied_upstream(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import BrokerSettings, RuntimeConfig, UpstreamConfig
    from mcp_broker.daemon import BrokerDaemon
    from mcp_broker.jsonrpc import JsonRpcRequest
    from mcp_broker.profiles import ToolExposureProfile

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
            "llm": ToolExposureProfile(name="llm", max_tools=10),
            "protected": ToolExposureProfile(
                name="protected",
                max_tools=10,
                allow_mutating_upstreams=("workspace-writer",),
            ),
        },
        upstreams={
            "workspace-writer": UpstreamConfig(
                name="workspace-writer",
                command="gws",
                args=["mcp"],
                mode="per_session",
                enabled=True,
                tool_prefix="workspace-writer",
                profiles=("protected",),
                mutating=True,
            )
        },
    )
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    calls: list[tuple[str, str]] = []

    def record_call(
        upstream_name: str,
        tool_name: str,
        arguments: dict[str, object],
        timeout_seconds: int,
    ) -> dict[str, object]:
        calls.append((upstream_name, tool_name))
        return {"content": []}

    daemon._call_upstream = record_call
    request = JsonRpcRequest(
        method="tools/call",
        id="call-google",
        params={
            "name": "workspace-writer.create_document",
            "arguments": {},
            "profile": "llm",
        },
        has_id=True,
    )

    response = daemon._handle_tools_call(request)

    assert response.error == {
        "code": -32000,
        "message": "tool prefix denied for profile llm: workspace-writer",
    }
    assert calls == []


def test_daemon_tools_call_rejects_unknown_profile_before_starting_upstream(
    tmp_path: Path,
) -> None:
    from mcp_broker.daemon import BrokerDaemon
    from mcp_broker.jsonrpc import JsonRpcRequest

    config = _empty_config(tmp_path)
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    calls: list[tuple[str, str]] = []

    def record_call(
        upstream_name: str,
        tool_name: str,
        arguments: dict[str, object],
        timeout_seconds: int,
    ) -> dict[str, object]:
        calls.append((upstream_name, tool_name))
        return {"content": []}

    daemon._call_upstream = record_call

    response = daemon._handle_tools_call(
        JsonRpcRequest(
            method="tools/call",
            id="unknown-profile",
            params={
                "name": "read-store.search",
                "arguments": {},
                "profile": "missing",
            },
            has_id=True,
        )
    )

    assert response.error == {"code": -32602, "message": "unknown profile: missing"}
    assert calls == []


def test_daemon_profile_from_params_without_config_returns_none(tmp_path: Path) -> None:
    from mcp_broker.daemon import BrokerDaemon

    daemon = BrokerDaemon(
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "broker.sock",
        broker_config=None,
    )

    assert daemon._profile_from_params({"profile": "llm"}) is None


def _empty_config(tmp_path: Path) -> BrokerConfig:
    from mcp_broker.config import BrokerSettings, RuntimeConfig

    return BrokerConfig(
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
