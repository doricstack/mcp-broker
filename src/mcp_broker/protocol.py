"""Core MCP protocol handlers for broker-owned methods."""

from __future__ import annotations

from dataclasses import dataclass

from mcp_broker.jsonrpc import JsonRpcRequest, JsonRpcResponse


SUPPORTED_PROTOCOL_VERSIONS = (
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
)


@dataclass
class McpProtocolHandler:
    server_name: str
    server_version: str
    initialized: bool = False
    _initialize_seen: bool = False

    def handle(self, request: JsonRpcRequest) -> JsonRpcResponse | None:
        if request.method == "initialize":
            return self._handle_initialize(request)
        if request.method == "notifications/initialized":
            self.initialized = True
            return None
        if not self._initialize_seen:
            return JsonRpcResponse.error(request.id, -32002, "Server not initialized")
        return JsonRpcResponse.error(request.id, -32601, f"unknown method: {request.method}")

    def _handle_initialize(self, request: JsonRpcRequest) -> JsonRpcResponse:
        params = request.params
        if not isinstance(params, dict) or "protocolVersion" not in params:
            return JsonRpcResponse.error(
                request.id,
                -32602,
                "initialize.params.protocolVersion is required",
            )
        requested_version = str(params["protocolVersion"])
        if requested_version not in SUPPORTED_PROTOCOL_VERSIONS:
            return JsonRpcResponse.error(
                request.id,
                -32602,
                "Unsupported protocol version",
            )
        self._initialize_seen = True
        return JsonRpcResponse.result(
            request.id,
            {
                "protocolVersion": requested_version,
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {
                    "name": self.server_name,
                    "version": self.server_version,
                },
            },
        )
