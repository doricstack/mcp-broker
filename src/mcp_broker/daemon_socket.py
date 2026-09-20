"""Bounded request framing for broker socket connections."""

import socket
import json
from typing import TYPE_CHECKING

from mcp_broker.elicitation import elicitation_scope
from mcp_broker.jsonrpc import JsonRpcResponse

if TYPE_CHECKING:
    from mcp_broker.daemon import BrokerDaemon

from mcp_broker.daemon_errors import BrokerRequestTooLarge


def read_request(connection: socket.socket, *, max_bytes: int, chunk_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0
    while True:
        chunk = connection.recv(chunk_bytes)
        if not chunk:
            break
        chunks.append(chunk)
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise BrokerRequestTooLarge(f"Request exceeds {max_bytes} bytes")
        if chunk.endswith(b"\n"):
            break
    return b"".join(chunks)


def handle_connection(daemon: "BrokerDaemon", connection: socket.socket) -> None:
    try:
        raw = daemon._read_request(connection)
    except socket.timeout:
        return
    except BrokerRequestTooLarge as exc:
        response = JsonRpcResponse.error(None, -32600, str(exc)).to_mapping()
        daemon._send_response(connection, response)
        daemon._write_request_log_safely(None, None, response)
        return
    if not raw:
        return
    try:
        request = json.loads(raw.decode("utf-8").strip())
    except json.JSONDecodeError:
        response = JsonRpcResponse.error(None, -32700, "Parse error").to_mapping()
        daemon._send_response(connection, response)
        daemon._write_request_log_safely(None, None, response)
    else:
        with elicitation_scope(connection, request, daemon._socket_max_request_bytes):
            response = daemon._handle_request(request)
        if response is not None:
            daemon._send_response(connection, response)
        daemon._write_request_log_safely(request.get("id"), request.get("method"), response)
        if request.get("method") == "broker/stop":
            daemon._wake_server()


def send_response(connection: socket.socket, response: dict[str, object]) -> None:
    try:
        connection.sendall(json.dumps(response, sort_keys=True).encode("utf-8") + b"\n")
    except (BrokenPipeError, ConnectionResetError):
        return
