"""Socket failures return errors and never fabricate an approval."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
import socket
from threading import Thread
import time
from uuid import uuid4

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
