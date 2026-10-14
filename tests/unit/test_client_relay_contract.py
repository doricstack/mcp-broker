"""Host replies stay attached to their originating broker connection."""

from concurrent.futures import Future, ThreadPoolExecutor
from io import BytesIO
import json
import logging
import os
from pathlib import Path
from queue import Queue
import socket
from threading import current_thread
from uuid import uuid4

import pytest

from mcp_broker.client import ClientShim, ClientShimError
from mcp_broker.client_relay import ClientRelay, _completed, _decode, _encode
from mcp_broker.schema import DEFAULT_SOCKET_MAX_REQUEST_BYTES

pytestmark = pytest.mark.unit


def wire(message):
    return json.dumps(message).encode() + b"\n"


class FiniteStream(BytesIO):
    """Reject incorrect read bounds and reads past the scripted exchange."""

    def __init__(self, payload, bound):
        super().__init__(payload)
        self.bound = bound
        self.read_bounds = []
        self.saw_eof = False

    def readline(self, size=-1):
        self.read_bounds.append(size)
        assert size == self.bound
        assert not self.saw_eof, "relay read again after broker EOF"
        payload = super().readline(size)
        self.saw_eof = not payload
        return payload


class FiniteConnection:
    """Socket boundary with finite input and no blocking operations."""

    def __init__(self, payload=b"", bound=DEFAULT_SOCKET_MAX_REQUEST_BYTES + 1):
        self.stream = FiniteStream(payload, bound)
        self.sent = []
        self.addresses = []
        self.thread_names = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.closed = True

    def connect(self, address):
        self.addresses.append(address)
        self.thread_names.append(current_thread().name)

    def makefile(self, mode):
        assert mode == "rb"
        return self.stream

    def sendall(self, payload):
        self.sent.append(payload)


class RecordingShim:
    """Record plain forwarding without opening a socket or waiting for a reply."""

    def __init__(self, response):
        self.response = response
        self.forwarded = []

    def forward_payload(self, payload):
        self.forwarded.append(payload)
        return self.response


class NonblockingFuture(Future):
    """An unfinished result lookup is a contract failure, never a test hang."""

    def result(self, timeout=None):
        assert self.done(), "relay waited for an unfinished future"
        return super().result(timeout=timeout)


def test_completed_leaves_unfinished_work_pending_without_waiting():
    future = NonblockingFuture()
    assert _completed(future) is False
    assert not future.done()
    assert not future.cancelled()


def test_encode_emits_compact_ascii_escaped_json_with_one_newline():
    value = {"id": "caf\u00e9", "result": [1, True, None, "line\nnext"]}
    encoded = _encode(value)
    assert encoded == b'{"id":"caf\\u00e9","result":[1,true,null,"line\\nnext"]}\n'
    assert encoded.count(b"\n") == 1
    assert json.loads(encoded) == value
    assert _encode({"text": "\U0001f680\ud800"}) == b'{"text":"\\ud83d\\ude80\\ud800"}\n'


def test_new_relay_has_open_host_input():
    relay = ClientRelay(ClientShim(Path("unused.sock")), BytesIO())
    assert relay._eof is False
    assert relay.capabilities == {}
    assert relay._pending == {}


def test_receive_reports_exact_early_close_error_and_closes_stream():
    peer = FiniteConnection()
    output = BytesIO()
    relay = ClientRelay(ClientShim(Path("unused.sock")), output)
    with pytest.raises(ClientShimError, match="^Broker closed before returning a response$"):
        relay._receive(peer, "call")
    assert peer.stream.read_bounds == [DEFAULT_SOCKET_MAX_REQUEST_BYTES + 1]
    assert peer.stream.closed
    assert output.getvalue() == b""


@pytest.mark.parametrize("over_limit", [False, True])
def test_receive_enforces_exact_byte_limit_and_stops_after_final_response(monkeypatch, over_limit):
    payload = b'{"jsonrpc":"2.0","id":"call","result":{"text":"\xc3\xa9"}}\n'
    limit = len(payload) - int(over_limit)
    monkeypatch.setattr("mcp_broker.client_relay.DEFAULT_SOCKET_MAX_REQUEST_BYTES", limit)
    peer = FiniteConnection(payload, limit + 1)
    output = BytesIO()
    relay = ClientRelay(ClientShim(Path("unused.sock")), output)
    if over_limit:
        with pytest.raises(ClientShimError, match="^Broker response exceeds message size limit$"):
            relay._receive(peer, "call")
        assert output.getvalue() == b""
    else:
        result = relay._receive(peer, "call")
        assert result is None
        assert output.getvalue() == payload
    assert peer.stream.read_bounds == [limit + 1]
    assert peer.stream.closed


def test_receive_forwards_prompt_then_final_response_without_reading_again():
    prompt = b'{"id":"approval","method":"elicitation/create"}\n'
    final = b'{"jsonrpc":"2.0","id":"call","result":{}}\n'
    peer = FiniteConnection(prompt + final)
    output = BytesIO()
    relay = ClientRelay(ClientShim(Path("unused.sock")), output)
    relay._receive(peer, "call")
    assert output.getvalue() == prompt + final
    assert peer.stream.read_bounds == [DEFAULT_SOCKET_MAX_REQUEST_BYTES + 1] * 2
    assert peer.sent == []
    assert relay._pending == {"approval": peer}


@pytest.mark.parametrize("reply,expected", [
    ({"result": {"action": "decline"}},
     b'{"jsonrpc":"2.0","id":"approval","result":{"action":"decline"}}\n'),
    ({"error": {"code": -32601, "message": "declined"}},
     b'{"jsonrpc":"2.0","id":"approval","error":{"code":-32601,"message":"declined"}}\n'),
])
def test_run_routes_each_host_reply_and_reaches_eof_without_forwarding(reply, expected):
    shim = RecordingShim(b'{"jsonrpc":"2.0","id":"wrong","result":{}}\n')
    output = BytesIO()
    peer = FiniteConnection()
    relay = ClientRelay(shim, output)
    relay._pending["approval"] = peer
    relay.run(BytesIO(wire({"jsonrpc": "2.0", "id": "approval", **reply})))
    assert peer.sent == [expected]
    assert shim.forwarded == []
    assert output.getvalue() == b""
    assert relay._pending == {}
    assert relay._eof is True


@pytest.mark.parametrize("frame", [
    {"jsonrpc": "2.0", "id": "call", "method": "ping", "result": {}},
    {"jsonrpc": "2.0", "id": "call", "method": "ping", "error": {}},
    {"jsonrpc": "2.0", "id": "call"},
    {"jsonrpc": "2.0", "result": {}},
])
def test_run_does_not_consume_non_reply_frames(frame):
    response = b'{"jsonrpc":"2.0","id":"call","result":{}}\n'
    shim = RecordingShim(response)
    output = BytesIO()
    relay = ClientRelay(shim, output)
    payload = wire(frame)
    relay.run(BytesIO(payload))
    assert shim.forwarded == [payload]
    assert output.getvalue() == (response if "id" in frame else b"")
    assert relay._eof is True


@pytest.mark.parametrize("method", ["tools/call", "tools/list"])
def test_run_finishes_worker_exchange_with_named_thread_and_exact_wire_bytes(monkeypatch, method):
    response = b'{"jsonrpc":"2.0","id":"call","result":{}}\n'
    peer = FiniteConnection(response)
    monkeypatch.setattr("mcp_broker.client_relay.socket.socket", lambda *_args: peer)
    shim = ClientShim(Path("broker.sock"), profile="test", session_id="session")
    output = BytesIO()
    relay = ClientRelay(shim, output)
    relay.capabilities = {"elicitation": {}}
    # Supply metadata so the expected wire bytes are independent of the host cwd.
    params = {"profile": "test", "broker_session_id": "session", "broker_client_cwd": "."}
    relay.run(BytesIO(wire({"jsonrpc": "2.0", "id": "call", "method": method, "params": params})))
    expected = (
        b'{"jsonrpc":"2.0","id":"call","method":"' + method.encode("ascii")
        + b'","params":{"profile":"test","broker_session_id":"session",'
        b'"broker_client_cwd":".","broker_client_capabilities":{"elicitation":{}}}}\n'
    )
    assert peer.sent == [expected]
    assert peer.addresses == [str(shim.socket_path)]
    assert len(peer.thread_names) == 1
    assert peer.thread_names[0].startswith("broker-client_")
    assert peer.closed
    assert output.getvalue() == response
    assert relay._eof is True


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
    future = NonblockingFuture()
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


def test_run_keeps_unfinished_workers_so_their_failure_reaches_the_caller(monkeypatch):
    first = NonblockingFuture()
    second = NonblockingFuture()
    second.set_result(None)
    failure = RuntimeError("host output failed after the next call started")
    submitted = []

    class ScriptedExecutor:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def submit(self, function, request):
            submitted.append((function, request["id"]))
            return first if len(submitted) == 1 else second

    monkeypatch.setattr(
        "mcp_broker.client_relay.ThreadPoolExecutor", lambda **_kwargs: ScriptedExecutor()
    )
    output = BytesIO()
    shim = ClientShim(Path("unused.sock"), profile="test", session_id="session")
    relay = ClientRelay(shim, output)
    relay.capabilities = {"elicitation": {}}

    def stdin():
        yield wire({"id": "first", "method": "tools/call"})
        assert not first.done()
        yield wire({"id": "second", "method": "tools/list"})
        # The first worker was still pending when the second was submitted.
        # Executor shutdown waits for workers but does not raise their errors.
        first.set_exception(failure)

    with pytest.raises(RuntimeError) as caught:
        relay.run(stdin())

    assert caught.value is failure
    assert str(caught.value) == "host output failed after the next call started"
    assert submitted == [(relay._exchange, "first"), (relay._exchange, "second")]
    assert relay._eof is True
    assert relay._pending == {}
    assert output.getvalue() == b""


def test_run_empty_input_returns_without_forwarding():
    shim = RecordingShim(b"unused response")
    output = BytesIO()
    relay = ClientRelay(shim, output)

    assert relay.run(BytesIO()) is None

    assert shim.forwarded == []
    assert output.getvalue() == b""
    assert relay._pending == {}
    assert relay._eof is True


@pytest.mark.parametrize("method,response_body,expected", [
    ("initialize", {"result": {}}, {"elicitation": {"form": {}}}),
    ("initialize", {"error": {"code": -32602, "message": "Invalid initialize"}},
     {"elicitation": {"url": {}}}),
    ("ping", {"result": {}}, {"elicitation": {"url": {}}}),
])
def test_run_changes_capabilities_only_after_a_successful_initialize(method, response_body, expected):
    response = wire({"jsonrpc": "2.0", "id": "request", **response_body})
    shim = RecordingShim(response)
    output = BytesIO()
    relay = ClientRelay(shim, output)
    relay.capabilities = {"elicitation": {"url": {}}}
    payload = wire({"jsonrpc": "2.0", "id": "request", "method": method,
                    "params": {"capabilities": {"elicitation": {"form": {}}}}})

    assert relay.run(BytesIO(payload)) is None

    assert relay.capabilities == expected
    assert shim.forwarded == [payload]
    assert output.getvalue() == response
    assert relay._eof is True


@pytest.mark.parametrize("fields", [
    {}, {"params": {}}, {"params": {"capabilities": {}}},
    {"params": None}, {"params": {"capabilities": None}},
])
def test_run_missing_capabilities_clear_prior_negotiation_and_finish_at_eof(fields):
    response = wire({"jsonrpc": "2.0", "id": "init", "result": {}})
    shim = RecordingShim(response)
    output = BytesIO()
    relay = ClientRelay(shim, output)
    relay.capabilities = {"elicitation": {"form": {}}}
    payload = wire({"jsonrpc": "2.0", "id": "init", "method": "initialize", **fields})

    assert relay.run(BytesIO(payload)) is None

    assert relay.capabilities == {}
    assert shim.forwarded == [payload]
    assert output.getvalue() == response
    assert relay._pending == {}
    assert relay._eof is True


@pytest.mark.parametrize("payload,expected", [
    (b"", {"jsonrpc": "2.0", "id": "call", "error": {
        "code": -32000,
        "message": "Broker transport failed: Broker closed before returning a response"}}),
    (b'{"jsonrpc":"2.0","id":"wrong","result":{}}\n',
     {"jsonrpc": "2.0", "id": "call", "error": {
         "code": -32000, "message": "Broker transport failed: Broker returned an invalid response"}}),
    (b'{"jsonrpc":"2.0","id":"call","result":{}}\n',
     {"jsonrpc": "2.0", "id": "call", "result": {}}),
])
def test_exchange_finishes_or_reports_transport_failure_and_cleans_only_its_prompts(
    monkeypatch, payload, expected,
):
    peer = FiniteConnection(payload)
    other = FiniteConnection()
    real_socket = socket.socket
    transport = []

    def open_socket(*args, **kwargs):
        # Inspect the effective transport, including OS defaults, not call spelling.
        with real_socket(*args, **kwargs) as connection:
            transport.append((connection.family, connection.type, connection.proto))
        return peer

    monkeypatch.setattr("mcp_broker.client_relay.socket.socket", open_socket)
    output = BytesIO()
    shim = ClientShim(Path("broker.sock"))
    relay = ClientRelay(shim, output)
    relay._pending = {"this-call": peer, "other-call": other}
    request = {"jsonrpc": "2.0", "id": "call", "method": "tools/call"}

    assert relay._exchange(request) is None

    assert transport == [(socket.AF_UNIX, socket.SOCK_STREAM, 0)]
    assert peer.addresses == [str(shim.socket_path)]
    assert peer.sent == [b'{"jsonrpc":"2.0","id":"call","method":"tools/call"}\n']
    assert peer.stream.read_bounds == [DEFAULT_SOCKET_MAX_REQUEST_BYTES + 1]
    assert peer.stream.closed
    assert peer.closed
    assert relay._pending == {"other-call": other}
    assert json.loads(output.getvalue()) == expected
    assert output.getvalue().count(b"\n") == 1


def test_exchange_returns_an_exact_error_when_socket_creation_fails(monkeypatch):
    def open_socket(*_args, **_kwargs):
        raise OSError("socket unavailable")

    monkeypatch.setattr("mcp_broker.client_relay.socket.socket", open_socket)
    output = BytesIO()
    relay = ClientRelay(ClientShim(Path("unused.sock")), output)

    assert relay._exchange({"id": "call", "method": "tools/call"}) is None

    assert json.loads(output.getvalue()) == {"jsonrpc": "2.0", "id": "call", "error": {
        "code": -32000, "message": "Broker transport failed: socket unavailable"}}
    assert output.getvalue().count(b"\n") == 1
    assert relay._pending == {}
