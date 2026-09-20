"""Approval must travel from the originating host to the waiting upstream."""

import json
import os
from pathlib import Path
import select
import subprocess
import sys
from uuid import uuid4

import pytest
import yaml

from mcp_broker.config import BrokerConfig
from mcp_broker.daemon import BrokerDaemon

pytestmark = pytest.mark.e2e

WORKER = '''import json, sys
capabilities = {}
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        capabilities = request["params"]["capabilities"]
        result = {"capabilities": {}, "protocolVersion": "2025-11-25"}
    elif method == "tools/list":
        result = {"tools": [{"name": "approve", "inputSchema": {"type": "object"}}]}
    elif "elicitation" not in capabilities:
        result = {"isError": True, "content": [{"type": "text", "text": "missing elicitation capability"}]}
    else:
        args = request["params"]["arguments"]
        outcomes = []
        for index in range(args.get("prompts", 1)):
            prompt = {"jsonrpc": "2.0", "id": "same-upstream-id", "method": "elicitation/create",
                      "params": {"message": args.get("label", "approve"), "requestedSchema": {"type": "object"}}}
            print(json.dumps(prompt), flush=True)
            reply = json.loads(sys.stdin.readline())
            assert reply["id"] == prompt["id"]
            outcomes.append(reply.get("result", reply.get("error")))
        result = {"content": [{"type": "text", "text": json.dumps(outcomes)}]}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


class Host:
    def __init__(self, socket_path):
        self.process = subprocess.Popen(
            [sys.executable, "-m", "mcp_broker.client", "--socket-path", str(socket_path),
             "--profile", "test"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0,
        )
        self.buffer = b""

    def send(self, request):
        self.process.stdin.write(json.dumps(request).encode() + b"\n")
        self.process.stdin.flush()

    def read(self, timeout=5):
        while b"\n" not in self.buffer:
            readable, _, _ = select.select([self.process.stdout], [], [], timeout)
            assert readable, "host never received a broker response"
            chunk = os.read(self.process.stdout.fileno(), 65536)
            assert chunk, "shim closed before returning a response"
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line)

    def initialize(self, capabilities):
        self.send({"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": capabilities}})
        assert self.read()["id"] == "init"
        self.send({"jsonrpc": "2.0", "id": "list", "method": "tools/list"})
        assert self.read()["id"] == "list"

    def call(self, request_id="call", **arguments):
        self.send({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                   "params": {"name": "sample.approve", "arguments": arguments}})

    def reply(self, prompt, action):
        self.send({"jsonrpc": "2.0", "id": prompt["id"], "result": {"action": action}})

    def close(self):
        self.process.terminate()
        self.process.communicate(timeout=5)


@pytest.fixture
def broker(tmp_path, request):
    worker = tmp_path / "approval_server.py"
    worker.write_text(WORKER)
    socket_path = Path("/tmp") / f"mb-approval-{uuid4().hex}.sock"
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump({
        "runtime": {"root": str(tmp_path / "runtime"), "socket_path": str(socket_path)},
        "profiles": {"test": {"max_tools": 20, "compact_tools_enabled": False}},
        "upstreams": {"sample": {"command": sys.executable, "args": [str(worker)],
            "mode": "per_session", "profiles": ["test"], "strict_initialization": True,
            "health": {"call_timeout_seconds": 3}, "relay_elicitation": True,
            **getattr(request, "param", {})}},
    }))
    config = BrokerConfig.from_file(config_path)
    daemon = BrokerDaemon(runtime_root=config.runtime.root, socket_path=socket_path, broker_config=config)
    daemon.start()
    hosts = []

    def connect(capabilities=None):
        host = Host(socket_path)
        hosts.append(host)
        host.initialize({"elicitation": {"form": {}}} if capabilities is None else capabilities)
        return host

    connect.stop = daemon.stop
    connect.daemon = daemon

    try:
        yield connect
    finally:
        for host in hosts:
            host.close()
        daemon.stop()


@pytest.mark.parametrize("action", ["accept", "decline", "cancel"])
def test_host_decision_reaches_upstream_after_list_first(broker, action):
    host = broker()
    host.call()
    prompt = host.read()
    assert prompt.get("method") == "elicitation/create", prompt
    host.reply(prompt, action)
    result = host.read()
    assert result["id"] == "call"
    assert json.loads(result["result"]["content"][0]["text"]) == [{"action": action}]


def test_queued_same_upstream_call_cannot_block_approval_reply(broker):
    host = broker()
    host.call("first", prompts=2)
    first = host.read()
    assert first.get("method") == "elicitation/create", first
    host.call("queued")
    host.reply(first, "decline")
    second = host.read()
    assert second["id"] != first["id"]
    host.reply(first, "accept")  # A stale approval must not answer the next prompt.
    host.reply(second, "cancel")
    responses = [host.read(), host.read()]
    result = next(value for value in responses if value.get("id") == "first")
    assert result["id"] == "first"
    assert json.loads(result["result"]["content"][0]["text"]) == [{"action": "decline"}, {"action": "cancel"}]
    queued = next(value for value in responses if value.get("method") == "elicitation/create")
    host.reply(queued, "decline")
    assert host.read()["id"] == "queued"


def test_identical_upstream_ids_are_isolated_between_hosts(broker):
    left, right = broker(), broker()
    left.call(label="left")
    right.call(label="right")
    a, b = left.read(), right.read()
    assert a.get("method") == b.get("method") == "elicitation/create", (a, b)
    assert a["id"] != b["id"]
    right.reply(a, "accept")  # A different host cannot answer this request.
    right.reply(b, "cancel")
    left.reply(a, "decline")
    assert json.loads(left.read()["result"]["content"][0]["text"]) == [{"action": "decline"}]
    assert json.loads(right.read()["result"]["content"][0]["text"]) == [{"action": "cancel"}]


def test_host_without_elicitation_support_does_not_advertise_it(broker):
    host = broker(capabilities={})
    host.call()
    result = host.read()
    assert result["result"]["isError"]
    assert result["result"]["content"][0]["text"] == "missing elicitation capability"


def test_approval_timeout_returns_original_call_error_and_resets_upstream(broker):
    host = broker()
    host.call("expired")
    expired = host.read()
    assert expired.get("method") == "elicitation/create", expired
    failure = host.read()
    assert failure["id"] == "expired"
    assert "error" in failure
    host.reply(expired, "accept")
    host.call("next")
    prompt = host.read()
    assert prompt.get("method") == "elicitation/create", prompt
    host.reply(prompt, "decline")
    assert host.read()["id"] == "next"


@pytest.mark.parametrize("reply", [
    {"result": {"action": "yes"}},
    {"result": {"action": "accept"}, "error": {"code": -1, "message": "bad"}},
    {"error": {"code": "bad", "message": "bad"}},
    {"result": {"action": "accept", "content": []}},
])
def test_malformed_host_reply_fails_closed_and_resets_upstream(broker, reply):
    host = broker()
    host.call("malformed")
    prompt = host.read()
    host.send({"jsonrpc": "2.0", "id": prompt["id"], **reply})
    failure = host.read()
    assert failure["id"] == "malformed"
    assert "error" in failure
    host.call("next")
    prompt = host.read()
    assert prompt.get("method") == "elicitation/create", prompt
    host.reply(prompt, "cancel")
    assert host.read()["id"] == "next"


def test_host_error_is_forwarded_without_becoming_approval(broker):
    host = broker()
    host.call()
    prompt = host.read()
    error = {"code": -32601, "message": "Host cannot review this request"}
    host.send({"jsonrpc": "2.0", "id": prompt["id"], "error": error})
    result = host.read()
    assert json.loads(result["result"]["content"][0]["text"]) == [error]


def test_disconnected_broker_returns_error_without_another_host_request(broker):
    host = broker()
    broker.stop()
    host.call("disconnected")
    result = host.read()
    assert result["id"] == "disconnected"
    assert "error" in result


@pytest.mark.parametrize("broker", [{"relay_elicitation": False, "mode": "shared"}], indirect=True)
def test_shared_upstream_keeps_state_when_hosts_have_different_capabilities(broker):
    left = broker()
    before = broker.daemon._stdio_upstreams["sample"].pid
    right = broker(capabilities={})
    for host in (left, right, left):
        host.call()
        result = host.read()
        assert result["result"]["content"][0]["text"] == "missing elicitation capability"
        assert broker.daemon._stdio_upstreams["sample"].pid == before
