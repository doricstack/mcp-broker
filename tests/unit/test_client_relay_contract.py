"""Host replies stay attached to their originating broker connection."""

from concurrent.futures import Future, ThreadPoolExecutor
from io import BytesIO
import json
import logging
import os
from pathlib import Path
from queue import Queue
import socket
from uuid import uuid4

import pytest

from mcp_broker.client import ClientShim, ClientShimError
from mcp_broker.client_relay import ClientRelay, _completed, _decode

pytestmark = pytest.mark.unit


def wire(message):
    return json.dumps(message).encode() + b"\n"


class HostOutput(BytesIO):
    """Expose flushed messages to the host without polling or sleeps."""

    def __init__(self):
        super().__init__()
        self.messages = Queue()
        self.offset = 0

    def flush(self):
        payload = self.getvalue()[self.offset:]
        self.offset += len(payload)
        self.messages.put(json.loads(payload))

    def read_message(self):
        return self.messages.get(timeout=3)


@pytest.fixture
def broker_peer():
    path = Path("/tmp") / f"mb-contract-{uuid4().hex}.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen()
        listener.settimeout(3)
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []

            def start(handler):
                def serve():
                    connection, _ = listener.accept()
                    with connection:
                        connection.settimeout(3)
                        with connection.makefile("rb") as stream:
                            handler(connection, stream)

                future = executor.submit(serve)
                futures.append(future)
                return future

            try:
                yield path, start
            finally:
                path.unlink(missing_ok=True)
                for future in futures:
                    future.result(timeout=4)


@pytest.mark.parametrize("reply", [
    {"result": {"action": "decline"}},
    {"error": {"code": -32601, "message": "Host declined review"}},
])
def test_run_multiplexes_calls_and_routes_approval_only_to_its_socket(broker_peer, reply):
    path, start = broker_peer
    output = HostOutput()
    relay = ClientRelay(ClientShim(path, profile="test", session_id="session"), output)
    capabilities = {"elicitation": {"form": {}}}
    requests = Queue()
    replies = Queue()

    def initialize(connection, stream):
        request = json.loads(stream.readline())
        assert request["method"] == "initialize"
        connection.sendall(wire({"jsonrpc": "2.0", "id": "init", "result": {}}))

    def tool(connection, stream):
        request = json.loads(stream.readline())
        requests.put(request)
        if request["method"] == "tools/call":
            prompt_id = f"approval-{request['id']}"
            connection.sendall(wire({"jsonrpc": "2.0", "id": prompt_id,
                                     "method": "elicitation/create", "params": {}}))
            replies.put(json.loads(stream.readline()))
        connection.sendall(wire({"jsonrpc": "2.0", "id": request["id"],
                                 "result": {"completed": request["id"]}}))

    init = start(initialize)

    def stdin():
        yield wire({"jsonrpc": "2.0", "id": "init", "method": "initialize",
                    "params": {"capabilities": {**capabilities, "sampling": {}}}})
        assert output.read_message() == {"jsonrpc": "2.0", "id": "init", "result": {}}
        init.result(timeout=3)
        listing = start(tool)
        yield wire({"jsonrpc": "2.0", "id": "list", "method": "tools/list"})
        assert output.read_message()["result"] == {"completed": "list"}
        listing.result(timeout=3)
        start(tool)
        yield wire({"jsonrpc": "2.0", "id": "first", "method": "tools/call", "params": {"name": "sample"}})
        first = output.read_message()
        start(tool)
        yield wire({"jsonrpc": "2.0", "id": "second", "method": "tools/call", "params": {"name": "sample"}})
        second = output.read_message()
        assert first["method"] == second["method"] == "elicitation/create"
        assert first["id"] != second["id"]
        yield wire({"jsonrpc": "2.0", "id": second["id"], **reply})
        assert output.read_message()["id"] == "second"
        yield wire({"jsonrpc": "2.0", "id": second["id"], "result": {"action": "accept"}})
        yield wire({"jsonrpc": "2.0", "id": first["id"], **reply})
        assert output.read_message()["id"] == "first"

    relay.run(stdin())

    outbound = [requests.get_nowait() for _ in range(3)]
    assert [request["method"] for request in outbound] == ["tools/list", "tools/call", "tools/call"]
    for request in outbound:
        assert request["params"]["broker_client_capabilities"] == capabilities
        assert request["params"]["profile"] == "test"
        assert request["params"]["broker_session_id"] == "session"
        assert request["params"]["broker_client_cwd"] == os.getcwd()
    assert [replies.get_nowait() for _ in range(2)] == [
        {"jsonrpc": "2.0", "id": "approval-second", **reply},
        {"jsonrpc": "2.0", "id": "approval-first", **reply},
    ]
    assert relay._pending == {}
    assert relay._eof is True
    assert output.messages.empty()


def test_eof_notifies_pending_call_and_waits_for_its_final_response(broker_peer):
    path, start = broker_peer
    output = HostOutput()
    relay = ClientRelay(ClientShim(path), output)
    relay.capabilities = {"elicitation": {}}
    replies = []

    def serve(connection, stream):
        request = json.loads(stream.readline())
        # Malformed params must reach the broker unchanged for validation.
        assert request["params"] == []
        connection.sendall(wire({"jsonrpc": "2.0", "id": "approval", "method": "elicitation/create"}))
        replies.append(json.loads(stream.readline()))
        connection.sendall(wire({"jsonrpc": "2.0", "id": "call", "error": replies[0]["error"]}))

    start(serve)

    def stdin():
        yield wire({"jsonrpc": "2.0", "id": "call", "method": "tools/call", "params": []})
        assert output.read_message()["id"] == "approval"
        assert set(relay._pending) == {"approval"}

    relay.run(stdin())
    assert replies == [{"jsonrpc": "2.0", "id": "approval", "error": {
        "code": -32000, "message": "Host input closed during elicitation"}}]
    assert output.read_message() == {"jsonrpc": "2.0", "id": "call", "error": replies[0]["error"]}
    assert relay._pending == {}
    assert relay._eof is True


def test_prompt_after_eof_is_refused_without_writing_it_to_host():
    left, right = socket.socketpair()
    output = BytesIO()
    relay = ClientRelay(ClientShim(Path("unused.sock")), output)
    relay.run(BytesIO())
    result = {"jsonrpc": "2.0", "id": "call", "result": {"cancelled": True}}
    with left, right:
        left.settimeout(3)
        right.settimeout(3)
        right.sendall(wire({"id": "late", "method": "elicitation/create"}) + wire(result))
        relay._receive(left, "call")
        assert json.loads(right.recv(4096)) == {"jsonrpc": "2.0", "id": "late", "error": {
            "code": -32000, "message": "Host input closed during elicitation"}}
    assert json.loads(output.getvalue()) == result
    assert relay._pending == {}


@pytest.mark.parametrize("request_id", [None, 1, [], "stale"])
def test_unmatched_reply_cannot_consume_another_pending_approval(request_id):
    left, right = socket.socketpair()
    relay = ClientRelay(ClientShim(Path("unused.sock")), BytesIO())
    with left, right:
        relay._pending["waiting"] = left
        relay._reply({"id": request_id, "result": {"action": "accept"}})
        assert relay._pending == {"waiting": left}
        right.setblocking(False)
        with pytest.raises(BlockingIOError):
            right.recv(4096)
        assert relay.stdout.getvalue() == b""


@pytest.mark.error_simulation
def test_closed_socket_discards_late_reply_and_eof_notification(caplog):
    left, right = socket.socketpair()
    relay = ClientRelay(ClientShim(Path("unused.sock")), BytesIO())
    with left, right, caplog.at_level(logging.DEBUG, logger="mcp_broker.client_relay"):
        left.close()
        relay._pending["late"] = left
        relay._reply({"id": "late", "result": {"action": "accept"}})
        assert relay._pending == {}
        assert "Discarded reply for a closed broker call" in caplog.messages
        relay._send_closed(left, "late")
        assert "Broker call closed before host EOF notification" in caplog.messages
        assert relay.stdout.getvalue() == b""


def test_completed_call_removes_only_its_own_pending_prompts(broker_peer):
    path, start = broker_peer
    output = BytesIO()
    relay = ClientRelay(ClientShim(path), output)
    final = {"jsonrpc": "2.0", "id": "call", "result": {"cancelled": True}}

    def serve(connection, stream):
        assert json.loads(stream.readline())["id"] == "call"
        connection.sendall(wire({"id": "abandoned", "method": "elicitation/create"}) + wire(final))

    start(serve)
    left, right = socket.socketpair()
    with left, right:
        relay._pending["other-call"] = left
        relay._exchange({"jsonrpc": "2.0", "id": "call", "method": "tools/call"})
        assert relay._pending == {"other-call": left}
    messages = [json.loads(line) for line in output.getvalue().splitlines()]
    assert messages[0]["id"] == "abandoned"
    assert messages[1] == final


@pytest.mark.parametrize("response", [
    {"jsonrpc": "2.0", "id": "call", "method": "unknown", "result": {}},
    {"jsonrpc": "2.0", "id": "call", "result": {}, "error": {}},
    {"jsonrpc": "2.0", "id": "call"},
    {"jsonrpc": "2.0", "id": 3, "method": "elicitation/create"},
])
def test_receive_rejects_malformed_response_without_host_output(response):
    left, right = socket.socketpair()
    output = BytesIO()
    relay = ClientRelay(ClientShim(Path("unused.sock")), output)
    with left, right:
        left.settimeout(3)
        right.sendall(wire(response))
        with pytest.raises(ClientShimError, match="^Broker returned an invalid response$"):
            relay._receive(left, "call")
    assert relay._pending == {}
    assert output.getvalue() == b""


@pytest.mark.parametrize("payload", [b"invalid", b"\xff", b"[]", b"null"])
def test_decode_malformed_or_non_object_input_cannot_route_a_reply(payload):
    assert _decode(payload) == {}


def test_completed_distinguishes_pending_success_and_failure():
    future = Future()
    assert _completed(future) is False
    future.set_result("response written")
    assert _completed(future) is True
    assert future.result() == "response written"
    failed = Future()
    failed.set_exception(RuntimeError("output failed"))
    with pytest.raises(RuntimeError, match="^output failed$"):
        _completed(failed)


@pytest.mark.parametrize("params,initial_response", [
    ({}, {"result": {}}),
    ([], {"result": {}}),
    ({"capabilities": []}, {"result": {}}),
    ({"capabilities": {"elicitation": True}}, {"result": {}}),
    ({"capabilities": {"elicitation": {}}}, {"error": {"code": -32602, "message": "Invalid initialize"}}),
])
def test_unnegotiated_hosts_use_plain_forwarding_and_suppress_notifications(broker_peer, params, initial_response):
    path, start = broker_peer
    output = BytesIO()
    relay = ClientRelay(ClientShim(path, session_id="session"), output)
    requests = Queue()

    def serve(connection, stream):
        request = json.loads(stream.readline())
        requests.put(request)
        response = initial_response if request.get("method") == "initialize" else {"result": {}}
        connection.sendall(wire({"jsonrpc": "2.0", "id": request.get("id"), **response}))

    for _ in range(3):
        start(serve)
    relay.run(BytesIO(b"".join(wire(request) for request in [
        {"jsonrpc": "2.0", "id": "init", "method": "initialize", "params": params},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": "call", "method": "tools/call", "params": {"name": "sample"}},
    ])))
    assert relay.capabilities == {}
    assert [json.loads(line) for line in output.getvalue().splitlines()] == [
        {"jsonrpc": "2.0", "id": "init", **initial_response},
        {"jsonrpc": "2.0", "id": "call", "result": {}},
    ]
    outbound = [requests.get_nowait() for _ in range(3)]
    assert [request["method"] for request in outbound] == ["initialize", "notifications/initialized", "tools/call"]
    assert "broker_client_capabilities" not in outbound[-1]["params"]
    assert outbound[-1]["params"]["broker_session_id"] == "session"


def test_unavailable_broker_returns_error_for_original_call(tmp_path):
    output = BytesIO()
    relay = ClientRelay(ClientShim(tmp_path / "missing.sock"), output)
    relay._exchange({"jsonrpc": "2.0", "id": "call", "method": "tools/call"})
    response = json.loads(output.getvalue())
    assert response["jsonrpc"] == "2.0"
    assert response["id"] == "call"
    assert response["error"]["code"] == -32000
    assert response["error"]["message"].startswith("Broker transport failed: ")
    assert "result" not in response
    assert relay._pending == {}
