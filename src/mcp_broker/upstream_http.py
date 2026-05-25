"""JSON-RPC over MCP Streamable HTTP for remote upstreams."""

from __future__ import annotations

from collections.abc import Mapping
import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any

from mcp_broker.config import UpstreamConfig
from mcp_broker.protocol import SUPPORTED_PROTOCOL_VERSIONS


MCP_PROTOCOL_VERSION_HEADER = "MCP-Protocol-Version"
MCP_SESSION_ID_HEADER = "Mcp-Session-Id"
RETRYABLE_HTTP_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


class HttpUpstreamError(Exception):
    """Raised when a remote HTTP upstream cannot complete a JSON-RPC call."""


class HttpUpstreamTimeout(HttpUpstreamError):
    """Raised when a remote HTTP upstream does not respond before the deadline."""


class HttpUpstreamClient:
    def __init__(
        self,
        upstream: UpstreamConfig,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.upstream = upstream
        self._environ = os.environ if environ is None else environ
        self._next_id = 0
        self._initialized = False
        self._session_id: str | None = None
        self._last_error: str | None = None

    def list_tools(self, *, timeout_seconds: int) -> list[dict[str, Any]]:
        try:
            result = self._jsonrpc_request(
                "tools/list",
                None,
                timeout_seconds=timeout_seconds,
            )
            tools = result.get("tools")
            if not isinstance(tools, list) or not all(
                isinstance(tool, dict) for tool in tools
            ):
                raise HttpUpstreamError(
                    f"upstream tools/list response invalid: {self.upstream.name}"
                )
        except Exception as exc:
            self._last_error = str(exc)
            raise
        self._last_error = None
        return tools

    def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        try:
            result = self._jsonrpc_request(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            self._last_error = str(exc)
            raise
        self._last_error = None
        return result

    def health_snapshot(self) -> dict[str, object]:
        return {
            "state": "reachable" if self._initialized else "configured",
            "pid": None,
            "cpu_percent": None,
            "memory_mb": None,
            "restarts": 0,
            "last_error": self._last_error,
        }

    def _jsonrpc_request(
        self,
        method: str,
        params: dict[str, Any] | None,
        *,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        if not self._initialized:
            self._initialize(timeout_seconds=timeout_seconds)
        request_id, payload = self._jsonrpc_payload(method, params)
        response = self._post_jsonrpc(
            payload,
            timeout_seconds=timeout_seconds,
            expected_id=request_id,
        )
        return self._result_from_response(response, request_id)

    def _initialize(self, *, timeout_seconds: int) -> None:
        request_id, payload = self._jsonrpc_payload(
            "initialize",
            {
                "protocolVersion": SUPPORTED_PROTOCOL_VERSIONS[0],
                "capabilities": {},
                "clientInfo": {"name": "mcp-broker", "version": "0.0.1"},
            },
        )
        response = self._post_jsonrpc(
            payload,
            timeout_seconds=timeout_seconds,
            expected_id=request_id,
        )
        self._result_from_response(response, request_id)
        self._post_notification(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout_seconds=timeout_seconds,
        )
        self._initialized = True

    def _jsonrpc_payload(
        self,
        method: str,
        params: dict[str, Any] | None,
    ) -> tuple[int, dict[str, Any]]:
        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        return request_id, payload

    def _post_notification(self, payload: dict[str, Any], *, timeout_seconds: int) -> None:
        response = self._http_post(payload, timeout_seconds=timeout_seconds)
        if response.status == 202 or not response.body:
            return
        parsed = _parse_http_response_body(response, self.upstream.name)
        error = parsed.get("error")
        if isinstance(error, dict):
            raise HttpUpstreamError(
                f"upstream notification failed: {self.upstream.name}: {error.get('message')}"
            )

    def _post_jsonrpc(
        self,
        payload: dict[str, Any],
        *,
        timeout_seconds: int,
        expected_id: int,
    ) -> dict[str, Any]:
        response = self._http_post(payload, timeout_seconds=timeout_seconds)
        parsed = _parse_http_response_body(response, self.upstream.name)
        if _is_jsonrpc_notification(parsed):
            raise HttpUpstreamError(f"upstream returned notification only: {self.upstream.name}")
        if parsed.get("id") != expected_id:
            raise HttpUpstreamError(
                f"upstream response id mismatch: {self.upstream.name}: "
                f"expected {expected_id}, received {_response_identity(parsed)}"
            )
        return parsed

    def _http_post(self, payload: dict[str, Any], *, timeout_seconds: int) -> "_HttpResponse":
        attempts_remaining = self.upstream.health.http_retry_attempts
        while True:
            try:
                return self._http_post_once(payload, timeout_seconds=timeout_seconds)
            except HttpUpstreamError as exc:
                if not _is_retryable_http_error(exc) or attempts_remaining <= 0:
                    raise
                attempts_remaining -= 1
                if self.upstream.health.http_retry_backoff_seconds:
                    _retry_wait(self.upstream.health.http_retry_backoff_seconds)

    def _http_post_once(
        self,
        payload: dict[str, Any],
        *,
        timeout_seconds: int,
    ) -> "_HttpResponse":
        headers = self._headers()
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        request = urllib.request.Request(
            self.upstream.command,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                response_body = response.read()
                session_id = response.headers.get(MCP_SESSION_ID_HEADER)
                if session_id:
                    self._session_id = session_id
                return _HttpResponse(
                    status=response.status,
                    content_type=response.headers.get("Content-Type", ""),
                    body=response_body,
                )
        except urllib.error.HTTPError as exc:
            status_code = exc.code
            exc.close()
            raise HttpUpstreamError(
                f"upstream HTTP request failed: {self.upstream.name}: status {status_code}"
            ) from exc
        except TimeoutError as exc:
            raise HttpUpstreamTimeout(f"upstream timed out: {self.upstream.name}") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise HttpUpstreamTimeout(f"upstream timed out: {self.upstream.name}") from exc
            raise HttpUpstreamError(
                f"upstream HTTP request failed: {self.upstream.name}: {exc.reason}"
            ) from exc

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            MCP_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0],
        }
        token = self._bearer_token()
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if self._session_id is not None:
            headers[MCP_SESSION_ID_HEADER] = self._session_id
        return headers

    def _bearer_token(self) -> str | None:
        resolved = self.upstream.resolve_environment(self._environ)
        if "AUTHORIZATION" in resolved:
            return resolved["AUTHORIZATION"].removeprefix("Bearer ")
        token_values = [
            value
            for target_name, value in resolved.items()
            if target_name.endswith("_TOKEN") or target_name.endswith("_ACCESS_TOKEN")
        ]
        if not token_values:
            return None
        if len(token_values) > 1:
            raise HttpUpstreamError(
                f"multiple bearer token env values configured for upstream {self.upstream.name}"
            )
        return token_values[0]

    def _result_from_response(
        self,
        response: dict[str, Any],
        request_id: int,
    ) -> dict[str, Any]:
        error = response.get("error")
        if isinstance(error, dict):
            raise HttpUpstreamError(
                f"upstream returned error: {self.upstream.name}: {error.get('message')}"
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise HttpUpstreamError(f"upstream response missing result: {self.upstream.name}")
        if response.get("id") != request_id:
            raise HttpUpstreamError(
                f"upstream response id mismatch: {self.upstream.name}: "
                f"expected {request_id}, received {_response_identity(response)}"
            )
        return result


class _HttpResponse:
    def __init__(self, *, status: int, content_type: str, body: bytes) -> None:
        self.status = status
        self.content_type = content_type
        self.body = body


def _parse_http_response_body(response: _HttpResponse, upstream_name: str) -> dict[str, Any]:
    if response.status == 202:
        raise HttpUpstreamError(f"upstream response missing result: {upstream_name}")
    if not response.body:
        raise HttpUpstreamError(f"upstream response missing body: {upstream_name}")
    if response.content_type.lower().startswith("text/event-stream"):
        return _parse_sse_response(response.body, upstream_name)
    loaded = json.loads(response.body.decode("utf-8"))
    if not isinstance(loaded, dict):
        raise HttpUpstreamError(f"upstream response must be an object: {upstream_name}")
    return loaded


def _parse_sse_response(body: bytes, upstream_name: str) -> dict[str, Any]:
    data_lines: list[str] = []
    for line in body.decode("utf-8").splitlines():
        if line.startswith("data:"):
            data_lines.append(line.removeprefix("data:").strip())
        if not line and data_lines:
            loaded = json.loads("\n".join(data_lines))
            if not isinstance(loaded, dict):
                raise HttpUpstreamError(f"upstream response must be an object: {upstream_name}")
            return loaded
    if data_lines:
        loaded = json.loads("\n".join(data_lines))
        if isinstance(loaded, dict):
            return loaded
    raise HttpUpstreamError(f"upstream SSE response missing data: {upstream_name}")


def _is_jsonrpc_notification(message: dict[str, Any]) -> bool:
    return "id" not in message and isinstance(message.get("method"), str)


def _response_identity(message: dict[str, Any]) -> str:
    parts = [f"id={message.get('id')!r}"]
    method = message.get("method")
    if isinstance(method, str):
        parts.append(f"method={method!r}")
    return ", ".join(parts)


def _is_retryable_http_error(error: HttpUpstreamError) -> bool:
    message = str(error)
    for status_code in RETRYABLE_HTTP_STATUS_CODES:
        if f"status {status_code}" in message:
            return True
    return False


def _retry_wait(backoff_seconds: int) -> None:
    threading.Event().wait(backoff_seconds)
