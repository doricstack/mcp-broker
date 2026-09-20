"""Request metadata must follow the call, never the cached upstream process."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

import pytest
import yaml

from mcp_broker.config import BrokerConfig
from mcp_broker.config_validate import validate_config_file
from mcp_broker.daemon import BrokerDaemon

pytestmark = pytest.mark.unit


@pytest.fixture
def configured(tmp_path):
    worker = tmp_path / "worker.py"
    worker.write_text('''import json, sys
for line in sys.stdin:
    r = json.loads(line)
    if "id" not in r:
        continue
    if r["method"] == "tools/list":
        result = {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]}
    else:
        result = {"content": [{"type": "text", "text": json.dumps(r["params"].get("_meta", {}))}]}
    print(json.dumps({"jsonrpc": "2.0", "id": r["id"], "result": result}), flush=True)
''')
    token = tmp_path / "token"
    token.write_text("configured-token")
    definition = {
        "command": sys.executable, "args": [str(worker)],
        "mode": "per_session", "profiles": ["test"],
        "forward_request_meta": ["session", "turn", "vendor/context", "auth"],
        "env_files": {"AUTH_TOKEN": str(token)},
        "request_meta": {"auth": "AUTH_TOKEN"},
    }
    data = {
        "schema_version": 1, "runtime": {"root": str(tmp_path / "runtime")},
        "profiles": {"test": {"max_tools": 20, "compact_tools_enabled": True}},
        "upstreams": {"runtime": definition},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data))
    return path, data


def call(daemon, meta, session="client-a", facade=True):
    arguments = {"name": "runtime.echo", "arguments": {}} if facade else {}
    response = daemon._handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"profile": "test", "broker_session_id": session,
                   "name": "broker.call_tool" if facade else "runtime.echo",
                   "arguments": arguments, "_meta": meta},
    })
    assert "error" not in response, response
    return json.loads(response["result"]["content"][0]["text"])


def test_config_schema_accepts_metadata_allowlist(configured):
    path, _ = configured
    schema = Path(__file__).resolve().parents[2] / "config/broker.schema.json"
    assert validate_config_file(path, schema).ok


@pytest.mark.parametrize("facade", [True, False])
def test_each_call_uses_current_metadata_and_configured_auth_wins(configured, facade):
    path, _ = configured
    config = BrokerConfig.from_file(path)
    daemon = BrokerDaemon(runtime_root=config.runtime.root,
                          socket_path=config.runtime.socket_path, broker_config=config)
    try:
        for turn in ("turn-one", "turn-two"):
            assert call(daemon, {"session": "origin", "turn": turn,
                                 "vendor/context": {"enabled": True},
                                 "auth": "untrusted", "private": "excluded"}, facade=facade) == {
                "session": "origin", "turn": turn,
                "vendor/context": {"enabled": True}, "auth": "configured-token",
            }
        assert call(daemon, {}, facade=facade) == {"auth": "configured-token"}
    finally:
        daemon.stop()


def test_parallel_sessions_do_not_share_metadata(configured):
    path, _ = configured
    config = BrokerConfig.from_file(path)
    daemon = BrokerDaemon(runtime_root=config.runtime.root,
                          socket_path=config.runtime.socket_path, broker_config=config)
    try:
        def run(index):
            identity = f"client-{index}"
            for turn in range(3):
                assert call(daemon, {"session": identity, "turn": turn}, session=identity) == {
                    "session": identity, "turn": turn, "auth": "configured-token"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, range(2)))
    finally:
        daemon.stop()


def test_forwarding_is_disabled_by_default(configured):
    path, data = configured
    data["upstreams"]["runtime"].pop("forward_request_meta")
    path.write_text(yaml.safe_dump(data))
    config = BrokerConfig.from_file(path)
    daemon = BrokerDaemon(runtime_root=config.runtime.root,
                          socket_path=config.runtime.socket_path, broker_config=config)
    try:
        assert call(daemon, {"session": "excluded"}) == {"auth": "configured-token"}
    finally:
        daemon.stop()


@pytest.mark.parametrize("value", ["session", [""], [1], ["bad name"]])
def test_invalid_metadata_allowlist_is_rejected(configured, value):
    path, data = configured
    data["upstreams"]["runtime"]["forward_request_meta"] = value
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="forward_request_meta"):
        BrokerConfig.from_file(path)


def test_metadata_allowlist_requires_stdio(configured):
    path, data = configured
    data["upstreams"]["runtime"].update(transport="http", mode="shared")
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="forward_request_meta requires transport: stdio"):
        BrokerConfig.from_file(path)


def test_metadata_context_restores_after_failure():
    from mcp_broker.request_metadata import (
        forwarded_request_metadata, request_metadata_scope,
    )

    with request_metadata_scope({"_meta": {"session": "outer"}}):
        with pytest.raises(RuntimeError, match="upstream failed"):
            with request_metadata_scope({"_meta": {"session": "inner"}}):
                raise RuntimeError("upstream failed")
        assert forwarded_request_metadata(("session",)) == {"session": "outer"}
    assert forwarded_request_metadata(("session",)) == {}


def test_malformed_metadata_is_rejected_without_starting_upstream(configured):
    path, _ = configured
    config = BrokerConfig.from_file(path)
    daemon = BrokerDaemon(runtime_root=config.runtime.root,
                          socket_path=config.runtime.socket_path, broker_config=config)
    response = daemon._handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "runtime.echo", "arguments": {}, "_meta": "bad"},
    })
    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == "tools/call _meta must be an object"
    assert not daemon._stdio_upstreams
