"""Multiplex tool requests while stdin continues accepting approval replies."""

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import socket
import threading
from typing import Any, BinaryIO, TYPE_CHECKING

from mcp_broker.schema import DEFAULT_SOCKET_MAX_REQUEST_BYTES

if TYPE_CHECKING:
    from mcp_broker.client import ClientShim


class ClientRelay:
    def __init__(self, shim: "ClientShim", stdout: BinaryIO):
        self.shim = shim
        self.stdout = stdout
        self.capabilities: dict[str, Any] = {}
        self._pending: dict[str, socket.socket] = {}
        self._lock = threading.Lock()
        self._output_lock = threading.Lock()
        self._eof = False

    def run(self, stdin: BinaryIO) -> None:
        from mcp_broker.client import _inject_broker_metadata, _is_jsonrpc_notification

        with ThreadPoolExecutor(thread_name_prefix="broker-client") as executor:
            futures = []
            try:
                for payload in stdin:
                    request = _decode(payload)
                    method = request.get("method")
                    if method is None and "id" in request and ("result" in request or "error" in request):
                        self._reply(request)
                        continue
                    if method in ("tools/call", "tools/list") and self.capabilities:
                        outbound = _decode(_inject_broker_metadata(
                            payload, self.shim.profile, self.shim.session_id))
                        if isinstance(outbound.get("params"), dict):
                            outbound["params"]["broker_client_capabilities"] = self.capabilities
                        futures = [future for future in futures if not _completed(future)]
                        futures.append(executor.submit(self._exchange, outbound))
                        continue
                    response = self.shim.forward_payload(payload)
                    if method == "initialize" and "result" in _decode(response):
                        params = request.get("params", {})
                        caps = params.get("capabilities", {}) if isinstance(params, dict) else {}
                        value = caps.get("elicitation") if isinstance(caps, dict) else None
                        self.capabilities = {"elicitation": value} if isinstance(value, dict) else {}
                    if not _is_jsonrpc_notification(payload):
                        self._write(response)
            finally:
                with self._lock:
                    self._eof = True
                    for request_id, connection in self._pending.items():
                        self._send_closed(connection, request_id)
                    self._pending.clear()
            for future in futures:
                future.result()

    def _reply(self, response: dict[str, Any]) -> None:
        request_id = response.get("id")
        if not isinstance(request_id, str):
            return
        with self._lock:
            connection = self._pending.pop(request_id, None)
            if connection is not None:
                try:
                    connection.sendall(_encode(response))
                except OSError:
                    # The call already timed out. A late approval never starts a new call.
                    logging.getLogger(__name__).debug("Discarded reply for a closed broker call")

    def _exchange(self, request: dict[str, Any]) -> None:
        from mcp_broker.client import ClientShimError

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.connect(str(self.shim.socket_path))
                connection.sendall(_encode(request))
                try:
                    self._receive(connection, request.get("id"))
                finally:
                    with self._lock:
                        self._pending = {key: value for key, value in self._pending.items()
                                         if value is not connection}
        except (OSError, ClientShimError) as exc:
            self._write(_encode({"jsonrpc": "2.0", "id": request.get("id"),
                "error": {"code": -32000, "message": f"Broker transport failed: {exc}"}}))

    def _receive(self, connection: socket.socket, request_id: object) -> None:
        from mcp_broker.client import ClientShimError

        with connection.makefile("rb") as stream:
            while True:
                payload = stream.readline(DEFAULT_SOCKET_MAX_REQUEST_BYTES + 1)
                if not payload:
                    raise ClientShimError("Broker closed before returning a response")
                if len(payload) > DEFAULT_SOCKET_MAX_REQUEST_BYTES:
                    raise ClientShimError("Broker response exceeds message size limit")
                response = _decode(payload)
                if response.get("method") == "elicitation/create" and isinstance(response.get("id"), str):
                    with self._lock:
                        if self._eof:
                            self._send_closed(connection, response["id"])
                            continue
                        self._pending[response["id"]] = connection
                    self._write(payload)
                    continue
                if (response.get("jsonrpc") != "2.0" or response.get("id") != request_id or "method" in response
                        or ("result" in response) == ("error" in response)):
                    raise ClientShimError("Broker returned an invalid response")
                self._write(payload)
                return

    def _send_closed(self, connection: socket.socket, request_id: str) -> None:
        try:
            connection.sendall(_encode({"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32000, "message": "Host input closed during elicitation"}}))
        except OSError:
            logging.getLogger(__name__).debug("Broker call closed before host EOF notification")

    def _write(self, payload: bytes) -> None:
        with self._output_lock:
            self.stdout.write(payload)
            self.stdout.flush()


def _encode(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n"


def _decode(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _completed(future) -> bool:
    if not future.done():
        return False
    future.result()
    return True
