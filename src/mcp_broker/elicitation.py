"""Call-scoped, fail-closed relay of upstream approval requests."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json
import socket
import time
from typing import Any
from uuid import uuid4


class ElicitationRelayError(Exception):
    """The host could not complete the approval exchange."""


_current: ContextVar["SocketElicitationRelay | None"] = ContextVar("elicitation_relay", default=None)


@contextmanager
def elicitation_scope(connection: socket.socket, request: object, max_bytes: int) -> Iterator[None]:
    params = request.get("params", {}) if isinstance(request, dict) else {}
    capabilities = params.get("broker_client_capabilities", {}) if isinstance(params, dict) else {}
    relay = SocketElicitationRelay(connection, capabilities, max_bytes)
    token = _current.set(relay)
    try:
        yield
    finally:
        _current.reset(token)


def client_capabilities(*, enabled: bool) -> dict[str, Any]:
    relay = _current.get()
    return {} if not enabled or relay is None else deepcopy(relay.capabilities)


def relay_request(request: dict[str, Any], deadline: float, *, enabled: bool) -> dict[str, Any]:
    relay = _current.get()
    if not enabled or relay is None or request.get("method") != "elicitation/create":
        return _error(request.get("id"), "Client request relay unavailable")
    return relay.request(request, deadline)


def _error(request_id: object, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": -32601, "message": message}}


class SocketElicitationRelay:
    def __init__(self, connection: socket.socket, capabilities: object, max_bytes: int):
        self.connection = connection
        self.max_bytes = max_bytes
        # No roots, sampling, or unrelated capabilities are implemented here.
        value = capabilities.get("elicitation") if isinstance(capabilities, dict) else None
        self.capabilities = {"elicitation": deepcopy(value)} if isinstance(value, dict) else {}

    def request(self, request: dict[str, Any], deadline: float) -> dict[str, Any]:
        capability = self.capabilities.get("elicitation")
        params = request.get("params", {})
        mode = params.get("mode", "form") if isinstance(params, dict) else None
        supported = capability is not None and (
            (mode == "form" and (not capability or isinstance(capability.get("form"), dict)))
            or (mode == "url" and isinstance(capability.get("url"), dict))
        )
        if not supported:
            return _error(request.get("id"), "Host does not support this elicitation mode")
        relay_id = f"broker-elicitation-{uuid4().hex}"
        outbound = dict(request, id=relay_id)
        previous_timeout = self.connection.gettimeout()
        try:
            self.connection.settimeout(max(0.001, deadline - time.monotonic()))
            self.connection.sendall(json.dumps(outbound).encode() + b"\n")
            response = self._read_reply(deadline)
            if not _valid_reply(response, relay_id):
                raise ElicitationRelayError("Invalid elicitation response from host")
            return dict(response, id=request["id"])
        except (OSError, ValueError) as exc:
            raise ElicitationRelayError("Elicitation host disconnected or timed out") from exc
        finally:
            self.connection.settimeout(previous_timeout)

    def _read_reply(self, deadline: float) -> Any:
        buffer = bytearray()
        while b"\n" not in buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ElicitationRelayError("Elicitation host timed out")
            self.connection.settimeout(remaining)
            chunk = self.connection.recv(min(65536, self.max_bytes + 1 - len(buffer)))
            if not chunk:
                raise ElicitationRelayError("Elicitation host disconnected")
            buffer.extend(chunk)
            if len(buffer) > self.max_bytes:
                raise ElicitationRelayError("Elicitation response exceeds request size limit")
        return json.loads(buffer)


def _valid_reply(response: object, request_id: str) -> bool:
    if not isinstance(response, dict) or response.get("jsonrpc") != "2.0":
        return False
    if response.get("id") != request_id or "method" in response:
        return False
    if ("result" in response) == ("error" in response):
        return False
    if "error" in response:
        error = response["error"]
        return (isinstance(error, dict) and type(error.get("code")) is int
                and isinstance(error.get("message"), str))
    result = response["result"]
    return (isinstance(result, dict) and result.get("action") in ("accept", "decline", "cancel")
            and ("content" not in result or isinstance(result["content"], dict)))
