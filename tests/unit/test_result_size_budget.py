"""Profile result-size settings: the client ceiling and the upstream budget hint."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import pytest
import yaml

from mcp_broker.config import BrokerConfig
from mcp_broker.config_validate import validate_config_file
from mcp_broker.daemon import BrokerDaemon

pytestmark = pytest.mark.unit

SCHEMA = Path(__file__).resolve().parents[2] / "config/broker.schema.json"
SIZE_META = "anthropic/maxResultSizeChars"
BUDGET_META = "mcp-broker/result_budget_chars"


# --- profile settings -------------------------------------------------------


def test_profile_settings_default_to_unset() -> None:
    from mcp_broker.profiles import ToolExposureProfile

    profile = ToolExposureProfile.from_mapping("p", {"max_tools": 5})

    assert profile.result_size_chars is None
    assert profile.result_budget_chars is None


def test_profile_settings_load_positive_integers() -> None:
    from mcp_broker.profiles import ToolExposureProfile

    profile = ToolExposureProfile.from_mapping(
        "p",
        {"max_tools": 5, "result_size_chars": 500000, "result_budget_chars": 1_000_000},
    )

    assert profile.result_size_chars == 500000
    assert profile.result_budget_chars == 1_000_000


@pytest.mark.parametrize("key", ["result_size_chars", "result_budget_chars"])
@pytest.mark.parametrize("value", [0, -1, "40000", 1.5, True])
def test_profile_settings_reject_non_positive_integers(key: str, value: Any) -> None:
    from mcp_broker.profiles import ToolExposureProfile

    with pytest.raises(ValueError, match=rf"^profiles\.p\.{key} must be a positive integer$"):
        ToolExposureProfile.from_mapping("p", {"max_tools": 5, key: value})


def test_result_size_chars_rejects_values_over_the_client_ceiling() -> None:
    from mcp_broker.profiles import ToolExposureProfile

    with pytest.raises(
        ValueError, match=r"^profiles\.p\.result_size_chars must be at most 500000$"
    ):
        ToolExposureProfile.from_mapping("p", {"max_tools": 5, "result_size_chars": 500001})


def test_hand_built_profile_is_validated_too() -> None:
    from mcp_broker.profiles import ToolExposureProfile

    with pytest.raises(ValueError, match=r"^profiles\.p\.result_budget_chars must be"):
        ToolExposureProfile(name="p", max_tools=5, result_budget_chars=0)


def _config_file(tmp_path: Path, profile: dict[str, Any]) -> Path:
    data = {
        "schema_version": 1,
        "runtime": {"root": str(tmp_path / "runtime")},
        "profiles": {"p": {"max_tools": 20, **profile}},
        "upstreams": {},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_config_file_and_schema_accept_both_settings(tmp_path: Path) -> None:
    path = _config_file(tmp_path, {"result_size_chars": 200000, "result_budget_chars": 40000})

    config = BrokerConfig.from_file(path)

    assert config.profiles["p"].result_size_chars == 200000
    assert config.profiles["p"].result_budget_chars == 40000
    assert validate_config_file(path, SCHEMA).ok


@pytest.mark.parametrize(
    "profile",
    [
        {"result_size_chars": 500001},
        {"result_size_chars": 0},
        {"result_size_chars": "big"},
        {"result_budget_chars": 0},
        {"result_budget_chars": 2.5},
    ],
)
def test_schema_rejects_invalid_settings(tmp_path: Path, profile: dict[str, Any]) -> None:
    from mcp_broker.config_validate import ConfigValidationError

    path = _config_file(tmp_path, profile)
    (key,) = profile

    with pytest.raises(ConfigValidationError, match=rf"profiles\.p\.{key}"):
        validate_config_file(path, SCHEMA)


# --- tools/list: the broker_call_tool size ceiling --------------------------


def test_call_tool_entry_declares_the_size_ceiling_only_when_set() -> None:
    from mcp_broker.tool_namespace import compact_broker_tool_definitions

    with_size = compact_broker_tool_definitions(
        broker_tool_name_style="snake", result_size_chars=200000
    )
    without = compact_broker_tool_definitions(broker_tool_name_style="snake")

    by_name = {tool["name"]: tool for tool in with_size}
    assert by_name["broker_call_tool"]["_meta"] == {SIZE_META: 200000}
    assert [tool for tool in with_size if "_meta" in tool] == [by_name["broker_call_tool"]]
    assert all("_meta" not in tool for tool in without)
    stripped = [{k: v for k, v in tool.items() if k != "_meta"} for tool in with_size]
    assert stripped == without


def _daemon(path: Path) -> BrokerDaemon:
    config = BrokerConfig.from_file(path)
    return BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )


@pytest.mark.parametrize("size", [None, 300000])
def test_daemon_tools_list_carries_the_profile_size_ceiling(
    tmp_path: Path, size: int | None
) -> None:
    profile: dict[str, Any] = {"compact_tools_enabled": True}
    if size is not None:
        profile["result_size_chars"] = size
    daemon = _daemon(_config_file(tmp_path, profile))
    daemon._protocol._initialize_seen = True
    try:
        response = daemon._handle_jsonrpc_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": {"profile": "p"},
        })
    finally:
        daemon.stop()

    tools = {tool["name"]: tool for tool in response["result"]["tools"]}
    if size is None:
        assert all("_meta" not in tool for tool in tools.values())
    else:
        assert tools["broker.call_tool"]["_meta"] == {SIZE_META: size}
        assert all("_meta" not in tool for name, tool in tools.items() if name != "broker.call_tool")


# --- tools/call: the upstream budget hint -----------------------------------


ECHO_WORKER = '''import json, sys
for line in sys.stdin:
    r = json.loads(line)
    if "id" not in r:
        continue
    if r["method"] == "tools/list":
        result = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
    else:
        result = {"content": [{"type": "text", "text": json.dumps(r["params"].get("_meta", {}))}]}
    print(json.dumps({"jsonrpc": "2.0", "id": r["id"], "result": result}), flush=True)
'''

# A strict upstream that knows nothing of _meta and answers the same either way.
IGNORING_WORKER = '''import json, sys
for line in sys.stdin:
    r = json.loads(line)
    if "id" not in r:
        continue
    if r["method"] == "tools/list":
        result = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
    else:
        result = {"content": [{"type": "text", "text": "fixed answer"}]}
    print(json.dumps({"jsonrpc": "2.0", "id": r["id"], "result": result}), flush=True)
'''


def _stdio_config(
    tmp_path: Path,
    *,
    budget: int | None,
    worker_source: str = ECHO_WORKER,
    mode: str = "per_session",
) -> Path:
    worker = tmp_path / "worker.py"
    worker.write_text(worker_source)
    token = tmp_path / "token"
    token.write_text("configured-token")
    profile: dict[str, Any] = {"max_tools": 20, "compact_tools_enabled": True}
    if budget is not None:
        profile["result_budget_chars"] = budget
    data = {
        "schema_version": 1,
        "runtime": {"root": str(tmp_path / "runtime")},
        "profiles": {"test": profile},
        "upstreams": {
            "runtime": {
                "command": sys.executable, "args": [str(worker)],
                "mode": mode, "profiles": ["test"],
                "forward_request_meta": ["turn", BUDGET_META],
                "env_files": {"AUTH_TOKEN": str(token)},
                "request_meta": {"auth": "AUTH_TOKEN"},
            },
        },
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def _call(daemon: BrokerDaemon, meta: dict[str, Any], *, facade: bool) -> dict[str, Any]:
    arguments = {"name": "runtime.echo", "arguments": {}} if facade else {}
    response = daemon._handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"profile": "test", "broker_session_id": "client-a",
                   "name": "broker.call_tool" if facade else "runtime.echo",
                   "arguments": arguments, "_meta": meta},
    })
    assert "error" not in response, response
    return response["result"]


@pytest.mark.parametrize("facade", [True, False])
@pytest.mark.parametrize("mode", ["per_session", "per_call"])
def test_budget_is_merged_into_forwarded_metadata(
    tmp_path: Path, facade: bool, mode: str
) -> None:
    daemon = _daemon(_stdio_config(tmp_path, budget=40000, mode=mode))
    try:
        # A caller cannot override the profile's budget, even through the allowlist.
        result = _call(daemon, {"turn": "t1", BUDGET_META: 999}, facade=facade)
        assert json.loads(result["content"][0]["text"]) == {
            "turn": "t1", BUDGET_META: 40000, "auth": "configured-token",
        }
        result = _call(daemon, {}, facade=facade)
        assert json.loads(result["content"][0]["text"]) == {
            BUDGET_META: 40000, "auth": "configured-token",
        }
    finally:
        daemon.stop()


@pytest.mark.parametrize("facade", [True, False])
def test_unset_budget_adds_nothing(tmp_path: Path, facade: bool) -> None:
    daemon = _daemon(_stdio_config(tmp_path, budget=None))
    try:
        result = _call(daemon, {"turn": "t1"}, facade=facade)
    finally:
        daemon.stop()

    assert json.loads(result["content"][0]["text"]) == {"turn": "t1", "auth": "configured-token"}


def test_upstream_that_ignores_meta_is_unaffected(tmp_path: Path) -> None:
    results = []
    for budget in (None, 40000):
        run_dir = tmp_path / str(budget)
        run_dir.mkdir()
        daemon = _daemon(_stdio_config(run_dir, budget=budget, worker_source=IGNORING_WORKER))
        try:
            results.append(_call(daemon, {}, facade=True))
        finally:
            daemon.stop()

    assert results[0] == results[1] == {"content": [{"type": "text", "text": "fixed answer"}]}


def test_budget_scope_restores_after_failure() -> None:
    from mcp_broker.request_metadata import (
        broker_request_metadata, broker_request_metadata_scope,
    )

    with broker_request_metadata_scope({BUDGET_META: 1}):
        with pytest.raises(RuntimeError, match="upstream failed"):
            with broker_request_metadata_scope({BUDGET_META: 2}):
                raise RuntimeError("upstream failed")
        assert broker_request_metadata() == {BUDGET_META: 1}
    assert broker_request_metadata() == {}


def test_result_budget_metadata_maps_the_profile_setting() -> None:
    from mcp_broker.profiles import ToolExposureProfile
    from mcp_broker.request_metadata import result_budget_metadata

    assert result_budget_metadata(None) == {}
    assert result_budget_metadata(ToolExposureProfile(name="p", max_tools=5)) == {}
    assert result_budget_metadata(
        ToolExposureProfile(name="p", max_tools=5, result_budget_chars=7)
    ) == {BUDGET_META: 7}


@pytest.mark.parametrize("budget", [None, 40000])
def test_http_upstream_call_carries_the_budget(
    monkeypatch: pytest.MonkeyPatch, budget: int | None
) -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.request_metadata import broker_request_metadata_scope
    from mcp_broker.upstream_http import HttpUpstreamClient

    client = HttpUpstreamClient(
        UpstreamConfig(name="remote", command="http://127.0.0.1:9/mcp", transport="http"),
        environ={},
    )
    sent: list[dict[str, Any]] = []

    def fake_request(method: str, params: dict[str, Any], *, timeout_seconds: int):
        sent.append({"method": method, "params": params})
        return {"content": []}

    monkeypatch.setattr(client, "_jsonrpc_request", fake_request)
    meta = {} if budget is None else {BUDGET_META: budget}
    with broker_request_metadata_scope(meta):
        assert client.call_tool("echo", {"q": 1}, timeout_seconds=2) == {"content": []}

    expected: dict[str, Any] = {"name": "echo", "arguments": {"q": 1}}
    if budget is not None:
        expected["_meta"] = {BUDGET_META: budget}
    assert sent == [{"method": "tools/call", "params": expected}]
