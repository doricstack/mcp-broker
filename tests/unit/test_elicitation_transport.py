"""Socket failures return errors and never fabricate an approval."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import socket
from threading import Thread
import time
from types import SimpleNamespace
from unittest.mock import Mock, call
from uuid import UUID, uuid4

import pytest

from mcp_broker.client import ClientShim
from mcp_broker.client_relay import ClientRelay
from mcp_broker.elicitation import (
    ElicitationRelayError, SocketElicitationRelay, client_capabilities,
    elicitation_scope, relay_request,
)

pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


@pytest.mark.parametrize("response", [b"", b"invalid\n", b"x" * 4097,
    b'{"id":"wrong","result":{}}\n', b'{"id":"original","result":{}}\n',
    b'{"jsonrpc":"1.0","id":"original","result":{}}\n'])
def test_async_exchange_returns_transport_error_on_early_close_or_bad_response(monkeypatch, response):
    monkeypatch.setattr("mcp_broker.client_relay.DEFAULT_SOCKET_MAX_REQUEST_BYTES", 4096)
    path = Path("/tmp") / f"mb-relay-{uuid4().hex}.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(path))
        listener.listen()

        def serve():
            connection, _ = listener.accept()
            with connection:
                connection.recv(4096)
                connection.sendall(response)

        thread = Thread(target=serve)
        thread.start()
        output = BytesIO()
        try:
            ClientRelay(ClientShim(path), output)._exchange({
                "jsonrpc": "2.0", "id": "original", "method": "tools/call"})
            result = json.loads(output.getvalue())
            assert result["id"] == "original"
            assert "error" in result
        finally:
            thread.join(timeout=2)
            path.unlink(missing_ok=True)


@pytest.mark.parametrize("reply", [b"x" * 129, b"\xff\n", b'{"jsonrpc":"2.0","id":"wrong","result":{"action":"accept"}}\n'])
def test_invalid_or_oversized_reply_never_returns_accept(reply):
    left, right = socket.socketpair()
    with left, right, ThreadPoolExecutor() as executor:
        relay = SocketElicitationRelay(left, {"elicitation": {}}, 128)
        future = executor.submit(relay.request, {
            "jsonrpc": "2.0", "id": 1, "method": "elicitation/create", "params": {}}, time.monotonic() + 1)
        prompt = right.recv(4096)
        assert json.loads(prompt)["method"] == "elicitation/create"
        right.sendall(reply)
        with pytest.raises(ElicitationRelayError):
            future.result(timeout=2)


def test_context_clears_and_unimplemented_client_requests_are_refused():
    left, right = socket.socketpair()
    with left, right:
        request = {"params": {"broker_client_capabilities": {"elicitation": {}, "sampling": {}}}}
        with elicitation_scope(left, request, 4096):
            assert client_capabilities(enabled=True) == {"elicitation": {}}
            assert client_capabilities(enabled=False) == {}
            refusal = relay_request({"id": 4, "method": "sampling/createMessage"},
                                    time.monotonic() + 1, enabled=True)
            assert refusal["error"]["code"] == -32601
        assert client_capabilities(enabled=True) == {}


def test_unsupported_url_mode_never_reaches_host():
    left, right = socket.socketpair()
    with left, right:
        relay = SocketElicitationRelay(left, {"elicitation": {"form": {}}}, 4096)
        response = relay.request({"id": 4, "params": {"mode": "url"}}, time.monotonic() + 1)
        assert response["error"]["code"] == -32601
        assert response == {"jsonrpc": "2.0", "id": 4, "error": {
            "code": -32601, "message": "Host does not support this elicitation mode"}}
        right.setblocking(False)
        with pytest.raises(BlockingIOError):
            right.recv(1)


def test_expired_deadline_fails_before_reading_a_host_reply():
    left, right = socket.socketpair()
    with left, right:
        right.settimeout(3)
        left.settimeout(0.75)
        relay = SocketElicitationRelay(left, {"elicitation": {}}, 4096)
        with pytest.raises(ElicitationRelayError, match="^Elicitation host timed out$"):
            relay.request({"id": "original", "method": "elicitation/create"},
                          time.monotonic() - 1)
        assert left.gettimeout() == 0.75
        prompt = json.loads(right.recv(4096))
        assert prompt["id"] != "original"
        assert prompt["method"] == "elicitation/create"


def test_host_eof_restores_timeout_and_does_not_fabricate_acceptance():
    left, right = socket.socketpair()
    with left, right, ThreadPoolExecutor() as executor:
        right.settimeout(3)
        left.settimeout(0.75)
        relay = SocketElicitationRelay(left, {"elicitation": {}}, 4096)
        future = executor.submit(relay.request, {"id": "original", "method": "elicitation/create"},
                                 time.monotonic() + 2)
        prompt = json.loads(right.recv(4096))
        right.shutdown(socket.SHUT_WR)
        with pytest.raises(ElicitationRelayError, match="^Elicitation host disconnected$"):
            future.result(timeout=3)
        assert left.gettimeout() == 0.75
        assert prompt["id"] != "original"
        assert prompt["method"] == "elicitation/create"


@pytest.mark.parametrize("reply", [
    [],
    {"jsonrpc": "1.0", "result": {"action": "accept"}},
    {"jsonrpc": "2.0", "method": "elicitation/create", "result": {"action": "accept"}},
    {"jsonrpc": "2.0"},
    {"jsonrpc": "2.0", "result": {"action": "accept"}, "error": {}},
    {"jsonrpc": "2.0", "error": []},
    {"jsonrpc": "2.0", "error": {"code": True, "message": "bad"}},
    {"jsonrpc": "2.0", "error": {"code": -1, "message": 1}},
    {"jsonrpc": "2.0", "result": []},
    {"jsonrpc": "2.0", "result": {"action": "yes"}},
    {"jsonrpc": "2.0", "result": {"action": "accept", "content": []}},
])
def test_malformed_matching_reply_is_rejected_and_timeout_restored(reply):
    left, right = socket.socketpair()
    with left, right, ThreadPoolExecutor() as executor:
        right.settimeout(3)
        left.settimeout(0.75)
        relay = SocketElicitationRelay(left, {"elicitation": {}}, 4096)
        future = executor.submit(relay.request, {"id": "original", "method": "elicitation/create"},
                                 time.monotonic() + 2)
        prompt = json.loads(right.recv(4096))
        outbound = dict(reply, id=prompt["id"]) if isinstance(reply, dict) else reply
        right.sendall(json.dumps(outbound).encode() + b"\n")
        with pytest.raises(ElicitationRelayError, match="^Invalid elicitation response from host$"):
            future.result(timeout=3)
        assert left.gettimeout() == 0.75
        assert prompt["id"] != "original"
        assert prompt["method"] == "elicitation/create"


@pytest.mark.parametrize("capabilities,params,reply", [
    ({"elicitation": {}}, {}, {"result": {"action": "accept", "content": {"approved": True}}}),
    ({"elicitation": {"form": {}}}, {"mode": "form"}, {"result": {"action": "decline"}}),
    ({"elicitation": {"url": {}}}, {"mode": "url"}, {"result": {"action": "cancel"}}),
    ({"elicitation": {}}, {}, {"error": {"code": -32601, "message": "Host refused"}}),
])
def test_supported_reply_roundtrip_preserves_decision_and_original_id(capabilities, params, reply):
    left, right = socket.socketpair()
    with left, right, ThreadPoolExecutor() as executor:
        right.settimeout(3)
        left.settimeout(0.75)
        relay = SocketElicitationRelay(left, capabilities, 4096)
        request = {"jsonrpc": "2.0", "id": 17, "method": "elicitation/create", "params": params}
        future = executor.submit(relay.request, request, time.monotonic() + 2)
        prompt = json.loads(right.recv(4096))
        response = {"jsonrpc": "2.0", "id": prompt["id"], **reply}
        right.sendall(json.dumps(response).encode() + b"\n")
        assert future.result(timeout=3) == {"jsonrpc": "2.0", "id": 17, **reply}
        assert prompt == {**request, "id": prompt["id"]}
        assert prompt["id"] != request["id"]
        assert left.gettimeout() == 0.75


def test_scope_routes_supported_request_and_clears_even_after_an_exception():
    left, right = socket.socketpair()
    with left, right, ThreadPoolExecutor() as executor:
        right.settimeout(3)
        request = {"id": "original", "method": "elicitation/create", "params": {}}
        capabilities = {"elicitation": {"form": {}}, "sampling": {}}

        def scoped_request():
            with pytest.raises(RuntimeError, match="^caller failed$"):
                with elicitation_scope(left, {"params": {"broker_client_capabilities": capabilities}}, 4096):
                    copied = client_capabilities(enabled=True)
                    copied["elicitation"]["form"]["changed"] = True
                    assert client_capabilities(enabled=True) == {"elicitation": {"form": {}}}
                    response = relay_request(request, time.monotonic() + 2, enabled=True)
                    assert response == {"jsonrpc": "2.0", "id": "original", "result": {"action": "decline"}}
                    raise RuntimeError("caller failed")
            assert client_capabilities(enabled=True) == {}
            return relay_request(request, time.monotonic() + 2, enabled=True)

        future = executor.submit(scoped_request)
        prompt = json.loads(right.recv(4096))
        right.sendall(json.dumps({"jsonrpc": "2.0", "id": prompt["id"],
                                 "result": {"action": "decline"}}).encode() + b"\n")
        assert future.result(timeout=3) == {"jsonrpc": "2.0", "id": "original", "error": {
            "code": -32601, "message": "Client request relay unavailable"}}
        assert capabilities == {"elicitation": {"form": {}}, "sampling": {}}


@pytest.fixture
def relay_socket(monkeypatch):
    """Control socket fragmentation and time without relying on OS scheduling."""
    monkeypatch.setattr("mcp_broker.elicitation.time", SimpleNamespace(monotonic=lambda: 10.0))
    monkeypatch.setattr("mcp_broker.elicitation.uuid4",
                        lambda: UUID("12345678-1234-5678-1234-567812345678"))
    connection = Mock(spec=socket.socket)
    connection.gettimeout.return_value = 0.75
    return connection


@pytest.mark.parametrize("remaining,send_timeout", [(0.25, 0.25), (1 / 2048, 0.001)])
def test_request_writes_exact_frame_and_restores_timeout(relay_socket, remaining, send_timeout):
    relay_socket.recv.return_value = (
        b'{"jsonrpc":"2.0","id":"broker-elicitation-12345678123456781234567812345678",'
        b'"result":{"action":"accept","content":{"approved":true}}}\n')
    relay = SocketElicitationRelay(relay_socket, {"elicitation": {}}, 4096)
    request = {"jsonrpc": "2.0", "id": 17, "method": "elicitation/create",
               "params": {"message": "Approve?\nSecond line"}}

    response = relay.request(request, 10.0 + remaining)

    assert response == {"jsonrpc": "2.0", "id": 17,
                        "result": {"action": "accept", "content": {"approved": True}}}
    assert request == {"jsonrpc": "2.0", "id": 17, "method": "elicitation/create",
                       "params": {"message": "Approve?\nSecond line"}}
    assert relay_socket.mock_calls == [
        call.gettimeout(), call.settimeout(send_timeout),
        call.sendall(b'{"jsonrpc": "2.0", "id": "broker-elicitation-12345678123456781234567812345678", '
                     b'"method": "elicitation/create", "params": {"message": "Approve?\\nSecond line"}}\n'),
        call.settimeout(remaining), call.recv(4097), call.settimeout(0.75),
    ]


@pytest.mark.parametrize("failure", [b"invalid\n", b"\xff\n", OSError("socket closed"),
                                     TimeoutError("socket timed out")])
def test_request_reports_exact_transport_error_and_restores_timeout(relay_socket, failure):
    if isinstance(failure, bytes):
        relay_socket.recv.return_value = failure
    else:
        relay_socket.recv.side_effect = failure
    relay = SocketElicitationRelay(relay_socket, {"elicitation": {}}, 4096)

    with pytest.raises(ElicitationRelayError,
                       match="^Elicitation host disconnected or timed out$") as caught:
        relay.request({"id": 17, "method": "elicitation/create"}, 10.25)

    if isinstance(failure, bytes):
        assert isinstance(caught.value.__cause__, ValueError)
    else:
        assert caught.value.__cause__ is failure
    assert relay_socket.settimeout.call_args_list == [call(0.25), call(0.25), call(0.75)]
    relay_socket.recv.assert_called_once_with(4097)


def test_request_restores_timeout_after_send_failure(relay_socket):
    failure = BrokenPipeError("host closed before prompt")
    relay_socket.sendall.side_effect = failure
    relay = SocketElicitationRelay(relay_socket, {"elicitation": {}}, 4096)

    with pytest.raises(ElicitationRelayError,
                       match="^Elicitation host disconnected or timed out$") as caught:
        relay.request({"id": 17, "method": "elicitation/create"}, 10.25)

    assert caught.value.__cause__ is failure
    assert relay_socket.settimeout.call_args_list == [call(0.25), call(0.75)]
    relay_socket.recv.assert_not_called()


def test_read_reply_rejects_exact_deadline_before_socket_io(relay_socket):
    relay = SocketElicitationRelay(relay_socket, {"elicitation": {}}, 128)

    with pytest.raises(ElicitationRelayError, match="^Elicitation host timed out$"):
        relay._read_reply(10.0)

    assert relay_socket.mock_calls == []


def test_read_reply_assembles_short_reads_at_exact_byte_limit(relay_socket):
    # Split a UTF-8 character and put the framing newline in its own read.
    parts = [b'{"content":"caf\xc3', b'\xa9","approved":true}', b'\n']
    size = sum(len(part) for part in parts)
    relay_socket.recv.side_effect = parts
    relay = SocketElicitationRelay(relay_socket, {"elicitation": {}}, size)

    assert relay._read_reply(10.25) == {"content": "caf\u00e9", "approved": True}
    assert relay_socket.recv.call_args_list == [
        call(size + 1), call(size + 1 - len(parts[0])), call(2)]
    assert relay_socket.settimeout.call_args_list == [call(0.25)] * 3


def test_read_reply_caps_reads_and_recomputes_remaining_budget(relay_socket):
    # A valid JSON string spanning the 64 KiB receive cap, with no short reads.
    wire = b'"' + b"a" * 65536 + b'"\n'
    relay_socket.recv.side_effect = [wire[:65536], wire[65536:]]
    relay = SocketElicitationRelay(relay_socket, {"elicitation": {}}, len(wire))

    assert relay._read_reply(10.25) == "a" * 65536
    assert relay_socket.recv.call_args_list == [call(65536), call(4)]
    assert relay_socket.settimeout.call_args_list == [call(0.25), call(0.25)]


@pytest.mark.parametrize("parts", [[b'"abc"\n'], [b'"abc"', b'\n']])
def test_read_reply_rejects_one_byte_over_limit_with_exact_error(relay_socket, parts):
    relay_socket.recv.side_effect = parts
    relay = SocketElicitationRelay(relay_socket, {"elicitation": {}}, 5)

    with pytest.raises(ElicitationRelayError,
                       match="^Elicitation response exceeds request size limit$"):
        relay._read_reply(10.25)

    expected_reads = [call(6)] if len(parts) == 1 else [call(6), call(1)]
    assert relay_socket.recv.call_args_list == expected_reads
    assert relay_socket.settimeout.call_args_list == [call(0.25)] * len(parts)


@pytest.mark.parametrize("prefix", [b"", b'{"action":"accept"}'])
def test_read_reply_requires_newline_before_eof(relay_socket, prefix):
    relay_socket.recv.side_effect = [prefix, b""] if prefix else [b""]
    relay = SocketElicitationRelay(relay_socket, {"elicitation": {}}, 128)

    with pytest.raises(ElicitationRelayError, match="^Elicitation host disconnected$"):
        relay._read_reply(10.25)

    expected_reads = [call(129), call(129 - len(prefix))] if prefix else [call(129)]
    assert relay_socket.recv.call_args_list == expected_reads
    assert relay_socket.settimeout.call_args_list == [call(0.25)] * len(expected_reads)
