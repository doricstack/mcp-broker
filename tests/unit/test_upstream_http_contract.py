from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from typing import Any

import pytest


pytestmark = pytest.mark.unit


def test_http_upstream_initializes_lists_tools_and_reuses_session_header() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.protocol import SUPPORTED_PROTOCOL_VERSIONS
    from mcp_broker.upstream_http import HttpUpstreamClient

    with FakeMcpHttpServer() as server:
        upstream = UpstreamConfig(
            name="remote-repo",
            command=server.url,
            transport="http",
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": "UNIT_GITHUB_TOKEN"},
        )
        client = HttpUpstreamClient(
            upstream,
            environ={"UNIT_GITHUB_TOKEN": "unit-test-token"},
        )

        tools = client.list_tools(timeout_seconds=2)

    assert tools == [{"name": "search_repositories", "description": "Search repositories"}]
    assert [record["method"] for record in server.records] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
    ]
    assert server.records[0]["headers"]["Authorization"] == "Bearer unit-test-token"
    assert server.records[0]["headers"]["Accept"] == "application/json, text/event-stream"
    assert server.records[0]["headers"]["Content-Type"] == "application/json"
    assert (
        _header(server.records[0]["headers"], "MCP-Protocol-Version")
        == SUPPORTED_PROTOCOL_VERSIONS[0]
    )
    assert "Mcp-Session-Id" not in server.records[0]["headers"]
    assert _header(server.records[2]["headers"], "Mcp-Session-Id") == "session-1"


def test_http_upstream_calls_tool_with_json_response() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_http import HttpUpstreamClient

    with FakeMcpHttpServer() as server:
        upstream = UpstreamConfig(name="remote-repo", command=server.url, transport="http")
        client = HttpUpstreamClient(upstream, environ={})

        response = client.call_tool(
            "search_repositories",
            {"query": "mcp-broker"},
            timeout_seconds=2,
        )

    assert response == {"content": [{"type": "text", "text": "repo result"}]}
    assert server.records[-1]["method"] == "tools/call"
    assert server.records[-1]["params"] == {
        "name": "search_repositories",
        "arguments": {"query": "mcp-broker"},
    }


def test_http_upstream_reuses_existing_initialization_for_later_calls() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_http import HttpUpstreamClient

    with FakeMcpHttpServer() as server:
        upstream = UpstreamConfig(name="remote-repo", command=server.url, transport="http")
        client = HttpUpstreamClient(upstream, environ={})

        tools = client.list_tools(timeout_seconds=2)
        response = client.call_tool(
            "search_repositories",
            {"query": "mcp-broker"},
            timeout_seconds=2,
        )

    assert tools == [{"name": "search_repositories", "description": "Search repositories"}]
    assert response == {"content": [{"type": "text", "text": "repo result"}]}
    assert [record["method"] for record in server.records] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    assert _header(server.records[2]["headers"], "Mcp-Session-Id") == "session-1"
    assert _header(server.records[3]["headers"], "Mcp-Session-Id") == "session-1"


def test_http_upstream_errors_do_not_include_token_values() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_http import HttpUpstreamClient, HttpUpstreamError

    with FakeMcpHttpServer(status=401) as server:
        upstream = UpstreamConfig(
            name="remote-repo",
            command=server.url,
            transport="http",
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": "UNIT_GITHUB_TOKEN"},
        )
        client = HttpUpstreamClient(
            upstream,
            environ={"UNIT_GITHUB_TOKEN": "unit-test-token"},
        )

        with pytest.raises(HttpUpstreamError) as exc:
            client.list_tools(timeout_seconds=2)

    assert "status 401" in str(exc.value)
    assert "unit-test-token" not in str(exc.value)
    assert [record["method"] for record in server.records] == ["initialize"]


def test_http_upstream_retries_transient_status_and_reuses_session_header() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.schema import HealthPolicy
    from mcp_broker.upstream_http import HttpUpstreamClient

    with FakeMcpHttpServer(method_statuses={"tools/list": [503, 200]}) as server:
        upstream = UpstreamConfig(
            name="remote",
            command=server.url,
            transport="http",
            health=HealthPolicy(http_retry_attempts=1, http_retry_backoff_seconds=0),
        )
        client = HttpUpstreamClient(upstream, environ={})

        tools = client.list_tools(timeout_seconds=2)

    assert tools == [{"name": "search_repositories", "description": "Search repositories"}]
    assert [record["method"] for record in server.records] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/list",
    ]
    assert _header(server.records[2]["headers"], "Mcp-Session-Id") == "session-1"
    assert _header(server.records[3]["headers"], "Mcp-Session-Id") == "session-1"


def test_http_upstream_retry_uses_configured_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.schema import HealthPolicy
    from mcp_broker import upstream_http
    from mcp_broker.upstream_http import HttpUpstreamClient

    sleeps: list[int] = []
    monkeypatch.setattr(upstream_http, "_retry_wait", sleeps.append)

    with FakeMcpHttpServer(method_statuses={"tools/list": [503, 200]}) as server:
        client = HttpUpstreamClient(
            UpstreamConfig(
                name="remote",
                command=server.url,
                transport="http",
                health=HealthPolicy(
                    http_retry_attempts=1,
                    http_retry_backoff_seconds=2,
                ),
            ),
            environ={},
        )

        client.list_tools(timeout_seconds=2)

    assert sleeps == [2]


def test_retry_wait_accepts_zero_backoff() -> None:
    from mcp_broker.upstream_http import _retry_wait

    _retry_wait(0)


def test_http_upstream_rejects_invalid_tools_and_records_health_error() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_http import HttpUpstreamClient, HttpUpstreamError

    with FakeMcpHttpServer(tools_result={"tools": {"bad": "shape"}}) as server:
        client = HttpUpstreamClient(
            UpstreamConfig(name="remote-repo", command=server.url, transport="http"),
            environ={},
        )

        with pytest.raises(HttpUpstreamError, match="upstream tools/list response invalid"):
            client.list_tools(timeout_seconds=2)

    assert client.health_snapshot() == {
        "state": "reachable",
        "pid": None,
        "cpu_percent": None,
        "memory_mb": None,
        "restarts": 0,
        "last_error": "upstream tools/list response invalid: remote-repo",
    }


def test_http_upstream_call_records_error_health() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_http import HttpUpstreamClient, HttpUpstreamError

    with FakeMcpHttpServer(call_error_message="bad call") as server:
        client = HttpUpstreamClient(
            UpstreamConfig(name="remote-repo", command=server.url, transport="http"),
            environ={},
        )

        with pytest.raises(HttpUpstreamError, match="bad call"):
            client.call_tool("search_repositories", {}, timeout_seconds=2)

    assert client.health_snapshot()["state"] == "reachable"
    assert client.health_snapshot()["last_error"] == "upstream returned error: remote-repo: bad call"


def test_http_upstream_rejects_notification_error_response() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_http import HttpUpstreamClient, HttpUpstreamError

    with FakeMcpHttpServer(notification_error_message="init denied") as server:
        client = HttpUpstreamClient(
            UpstreamConfig(name="remote-repo", command=server.url, transport="http"),
            environ={},
        )

        with pytest.raises(HttpUpstreamError, match="upstream notification failed: remote-repo"):
            client.list_tools(timeout_seconds=2)


def test_http_upstream_rejects_notification_only_and_id_mismatch_responses() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_http import HttpUpstreamClient, HttpUpstreamError

    with FakeMcpHttpServer(list_notification_only=True) as notification_server:
        notification_client = HttpUpstreamClient(
            UpstreamConfig(
                name="remote-repo",
                command=notification_server.url,
                transport="http",
            ),
            environ={},
        )

        with pytest.raises(HttpUpstreamError, match="upstream returned notification only"):
            notification_client.list_tools(timeout_seconds=2)

    with FakeMcpHttpServer(list_response_id="wrong") as mismatch_server:
        mismatch_client = HttpUpstreamClient(
            UpstreamConfig(name="remote-repo", command=mismatch_server.url, transport="http"),
            environ={},
        )

        with pytest.raises(HttpUpstreamError, match="expected 1, received id='wrong'"):
            mismatch_client.list_tools(timeout_seconds=2)


def test_http_upstream_auth_header_accepts_authorization_and_rejects_ambiguous_tokens() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_http import HttpUpstreamClient, HttpUpstreamError

    direct = HttpUpstreamClient(
        UpstreamConfig(
            name="direct",
            command="https://example.invalid/mcp",
            transport="http",
            env={"AUTHORIZATION": "UNIT_AUTHORIZATION"},
        ),
        environ={"UNIT_AUTHORIZATION": "Bearer direct-token"},
    )
    ambiguous = HttpUpstreamClient(
        UpstreamConfig(
            name="ambiguous",
            command="https://example.invalid/mcp",
            transport="http",
            env={
                "FIRST_TOKEN": "UNIT_FIRST_TOKEN",
                "SECOND_TOKEN": "UNIT_SECOND_TOKEN",
            },
        ),
        environ={
            "UNIT_FIRST_TOKEN": "one",
            "UNIT_SECOND_TOKEN": "two",
        },
    )

    assert direct._headers()["Authorization"] == "Bearer direct-token"
    with pytest.raises(HttpUpstreamError, match="multiple bearer token env values"):
        ambiguous._headers()


def test_http_upstream_result_validation_rejects_missing_result_and_id_mismatch() -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_http import HttpUpstreamClient, HttpUpstreamError

    client = HttpUpstreamClient(
        UpstreamConfig(name="remote-repo", command="https://example.invalid/mcp", transport="http"),
        environ={},
    )

    with pytest.raises(HttpUpstreamError, match="upstream response missing result"):
        client._result_from_response({"jsonrpc": "2.0", "id": 0, "result": []}, 0)
    with pytest.raises(
        HttpUpstreamError,
        match="expected 0, received id='wrong', method='tools/list'",
    ):
        client._result_from_response(
            {
                "jsonrpc": "2.0",
                "id": "wrong",
                "method": "tools/list",
                "result": {},
            },
            0,
        )


@pytest.mark.error_simulation
def test_http_upstream_maps_urlopen_timeout_and_url_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker import upstream_http
    from mcp_broker.upstream_http import HttpUpstreamClient, HttpUpstreamError, HttpUpstreamTimeout

    client = HttpUpstreamClient(
        UpstreamConfig(name="remote-repo", command="https://example.invalid/mcp", transport="http"),
        environ={},
    )

    for raised in (
        TimeoutError("slow"),
        upstream_http.urllib.error.URLError(TimeoutError("slow")),
    ):
        monkeypatch.setattr(
            upstream_http.urllib.request,
            "urlopen",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(raised),
        )
        with pytest.raises(HttpUpstreamTimeout, match="upstream timed out: remote-repo"):
            client._http_post({"jsonrpc": "2.0", "id": 0, "method": "tools/list"}, timeout_seconds=1)

    monkeypatch.setattr(
        upstream_http.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            upstream_http.urllib.error.URLError("dns failed")
        ),
    )
    with pytest.raises(HttpUpstreamError, match="dns failed"):
        client._http_post({"jsonrpc": "2.0", "id": 0, "method": "tools/list"}, timeout_seconds=1)


def test_http_response_parsing_rejects_invalid_bodies() -> None:
    from mcp_broker.upstream_http import (
        _HttpResponse,
        _parse_http_response_body,
        _parse_sse_response,
        HttpUpstreamError,
    )

    with pytest.raises(HttpUpstreamError, match="missing result"):
        _parse_http_response_body(
            _HttpResponse(status=202, content_type="application/json", body=b""),
            "remote-repo",
        )
    with pytest.raises(HttpUpstreamError, match="missing body"):
        _parse_http_response_body(
            _HttpResponse(status=200, content_type="application/json", body=b""),
            "remote-repo",
        )
    with pytest.raises(HttpUpstreamError, match="must be an object"):
        _parse_http_response_body(
            _HttpResponse(status=200, content_type="application/json", body=b"[]"),
            "remote-repo",
        )
    with pytest.raises(HttpUpstreamError, match="must be an object"):
        _parse_sse_response(b"data: []\n\n", "remote-repo")
    with pytest.raises(HttpUpstreamError, match="missing data"):
        _parse_sse_response(b"event: ping\n\n", "remote-repo")
    with pytest.raises(HttpUpstreamError, match="missing data"):
        _parse_sse_response(b"data: []", "remote-repo")
    assert _parse_sse_response(
        b"data: {\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{}}",
        "remote-repo",
    ) == {"jsonrpc": "2.0", "id": 1, "result": {}}


def test_http_notification_accepts_non_error_jsonrpc_body(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker import upstream_http
    from mcp_broker.upstream_http import HttpUpstreamClient

    client = HttpUpstreamClient(
        UpstreamConfig(
            name="remote-repo",
            command="http://127.0.0.1:1/mcp",
            transport="http",
            tool_prefix="remote-repo",
        ),
        environ={},
    )
    monkeypatch.setattr(
        client,
        "_http_post",
        lambda *_args, **_kwargs: upstream_http._HttpResponse(
            status=200,
            content_type="application/json",
            body=b'{"jsonrpc":"2.0","result":{}}',
        ),
    )

    client._post_notification(
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        timeout_seconds=1,
    )


class FakeMcpHttpServer:
    def __init__(
        self,
        *,
        status: int = 200,
        tools_result: dict[str, Any] | None = None,
        call_error_message: str | None = None,
        notification_error_message: str | None = None,
        list_notification_only: bool = False,
        list_response_id: int | str | None = None,
        method_statuses: dict[str, list[int]] | None = None,
    ) -> None:
        self.status = status
        self.method_statuses = {
            method: list(statuses) for method, statuses in (method_statuses or {}).items()
        }
        self.tools_result = tools_result or {
            "tools": [
                {
                    "name": "search_repositories",
                    "description": "Search repositories",
                }
            ]
        }
        self.call_error_message = call_error_message
        self.notification_error_message = notification_error_message
        self.list_notification_only = list_notification_only
        self.list_response_id = list_response_id
        self.records: list[dict[str, Any]] = []
        self._server = _FakeThreadingHttpServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever)
        self._thread.daemon = True

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/mcp"

    def __enter__(self) -> "FakeMcpHttpServer":
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._server.shutdown()
        self._thread.join(timeout=2)
        self._server.server_close()

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.close_connection = True
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                owner.records.append(
                    {
                        "method": payload.get("method"),
                        "params": payload.get("params"),
                        "headers": dict(self.headers),
                    }
                )
                method_statuses = owner.method_statuses.get(str(payload.get("method")), [])
                status = method_statuses.pop(0) if method_statuses else owner.status
                if status != 200:
                    body = b"auth failed"
                    self.send_response(status)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if payload.get("method") == "initialize":
                    self._send_json(
                        payload["id"],
                        {
                            "protocolVersion": "2025-11-25",
                            "capabilities": {},
                            "serverInfo": {"name": "fake-remote-repo", "version": "1.0.0"},
                        },
                        session_id="session-1",
                    )
                    return
                if payload.get("method") == "notifications/initialized":
                    if owner.notification_error_message is not None:
                        self._send_error(payload.get("id"), owner.notification_error_message)
                        return
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    return
                if payload.get("method") == "tools/list":
                    if owner.list_notification_only:
                        self._send_raw_json({"jsonrpc": "2.0", "method": "notifications/progress"})
                        return
                    self._send_sse(payload["id"], owner.tools_result)
                    return
                if payload.get("method") == "tools/call":
                    if owner.call_error_message is not None:
                        self._send_error(payload["id"], owner.call_error_message)
                        return
                    self._send_json(
                        payload["id"],
                        {"content": [{"type": "text", "text": "repo result"}]},
                    )
                    return
                self.send_response(500)
                self.send_header("Content-Length", "0")
                self.send_header("Connection", "close")
                self.end_headers()

            def log_message(self, *_args: object) -> None:
                return

            def _send_json(
                self,
                request_id: int,
                result: dict[str, Any],
                *,
                session_id: str | None = None,
            ) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Connection", "close")
                if session_id is not None:
                    self.send_header("Mcp-Session-Id", session_id)
                body = json.dumps(
                    {"jsonrpc": "2.0", "id": request_id, "result": result},
                ).encode("utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_sse(self, request_id: int, result: dict[str, Any]) -> None:
                response_id = owner.list_response_id
                if response_id is None:
                    response_id = request_id
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                body = (
                    b"event: message\n"
                    + b"data: "
                    + json.dumps(
                        {"jsonrpc": "2.0", "id": response_id, "result": result},
                    ).encode("utf-8")
                    + b"\n\n"
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_error(self, request_id: int | None, message: str) -> None:
                self._send_raw_json(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32000, "message": message},
                    }
                )

            def _send_raw_json(self, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Connection", "close")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler


class _FakeThreadingHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _header(headers: dict[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    raise KeyError(name)
