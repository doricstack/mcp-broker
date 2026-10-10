"""Relay configuration and process reuse cannot leak host capabilities."""

import socket
import sys

import pytest

from mcp_broker.config import UpstreamConfig
from mcp_broker.config_modes import (
    parse_relay_elicitation, validate_upstream_session_mode, validate_upstream_transport_mode,
)
from mcp_broker.elicitation import elicitation_scope
from mcp_broker.upstream_stdio import StdioUpstreamProcess

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", [None, 0, 1, "true", {}, []])
def test_relay_flag_requires_boolean(value):
    with pytest.raises(ValueError) as error:
        parse_relay_elicitation("sample", "per_session", "stdio", value)
    assert str(error.value) == "upstreams.sample.relay_elicitation must be a boolean"


@pytest.mark.parametrize("mode", ["shared", "per_session", "per_call"])
@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_relay_opt_in_requires_isolated_stdio(mode, transport):
    assert parse_relay_elicitation("sample", mode, transport, False) is False
    if transport == "stdio" and mode in {"per_session", "per_call"}:
        assert parse_relay_elicitation("sample", mode, transport, True) is True
    else:
        with pytest.raises(ValueError) as error:
            parse_relay_elicitation("sample", mode, transport, True)
        assert str(error.value) == "upstreams.sample.relay_elicitation requires isolated stdio mode"


@pytest.mark.parametrize("mode", ["shared", "per_session", "per_call"])
@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_per_call_transport_validation(mode, transport):
    if mode == "per_call" and transport != "stdio":
        with pytest.raises(ValueError) as error:
            validate_upstream_transport_mode("sample", mode, transport)
        assert str(error.value) == "upstreams.sample.mode per_call requires transport: stdio"
    else:
        assert validate_upstream_transport_mode("sample", mode, transport) is None


@pytest.mark.parametrize("mode", ["shared", "per_session", "per_call"])
def test_session_environment_requires_an_isolated_process(mode):
    assert validate_upstream_session_mode("sample", mode, {}) is None
    if mode == "shared":
        with pytest.raises(ValueError) as error:
            validate_upstream_session_mode("sample", mode, {"SESSION": "session"})
        assert str(error.value) == "upstreams.sample.session_env requires mode: per_session or per_call"
    else:
        assert validate_upstream_session_mode("sample", mode, {"SESSION": "session"}) is None


def test_cached_upstream_restarts_only_when_host_capabilities_change(tmp_path):
    worker = tmp_path / "capabilities.py"
    worker.write_text('''import json, os, sys
capabilities = {}
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    if request["method"] == "initialize":
        capabilities = request["params"]["capabilities"]
        result = {"capabilities": {}}
    else:
        result = {"pid": os.getpid(), "capabilities": capabilities}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
''')
    client = StdioUpstreamProcess(UpstreamConfig(
        name="sample", command=sys.executable, args=(str(worker),), mode="per_session",
        relay_elicitation=True, strict_initialization=True), runtime_state_dir=tmp_path / "state")
    left, right = socket.socketpair()
    with left, right:
        try:
            request = {"params": {"broker_client_capabilities": {"elicitation": {"form": {}}}}}
            with elicitation_scope(left, request, 4096):
                first = client.call_tool("inspect", {}, timeout_seconds=3)
                old_process = client._process
                same = client.call_tool("inspect", {}, timeout_seconds=3)
            with elicitation_scope(left, {"params": {}}, 4096):
                changed = client.call_tool("inspect", {}, timeout_seconds=3)
                same_changed = client.call_tool("inspect", {}, timeout_seconds=3)
            assert first["capabilities"] == {"elicitation": {"form": {}}}
            assert same == first
            assert changed["capabilities"] == {}
            assert changed["pid"] != first["pid"]
            assert old_process.poll() is not None
            assert same_changed == changed
            assert client._client_capabilities == {}
        finally:
            client.stop()
