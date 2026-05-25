import pytest


pytestmark = pytest.mark.unit


def test_protocol_initialize_negotiates_supported_version() -> None:
    from mcp_broker.jsonrpc import JsonRpcRequest
    from mcp_broker.protocol import McpProtocolHandler

    handler = McpProtocolHandler(server_name="mcp-broker", server_version="0.0.1")
    request = JsonRpcRequest.from_mapping(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "unit-test", "version": "1.0"},
            },
        }
    )

    response = handler.handle(request)

    assert response is not None
    assert response.result == {
        "protocolVersion": "2025-03-26",
        "capabilities": {"tools": {"listChanged": True}},
        "serverInfo": {"name": "mcp-broker", "version": "0.0.1"},
    }


def test_protocol_rejects_unsupported_version_and_preinitialize_methods() -> None:
    from mcp_broker.jsonrpc import JsonRpcRequest
    from mcp_broker.protocol import McpProtocolHandler

    handler = McpProtocolHandler(server_name="mcp-broker", server_version="0.0.1")

    unsupported = handler.handle(
        JsonRpcRequest.from_mapping(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "1900-01-01"},
            }
        )
    )
    assert unsupported is not None
    assert unsupported.error == {
        "code": -32602,
        "message": "Unsupported protocol version",
    }

    premature = handler.handle(
        JsonRpcRequest.from_mapping(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        )
    )
    assert premature is not None
    assert premature.error == {
        "code": -32002,
        "message": "Server not initialized",
    }


def test_protocol_initialized_notification_updates_state() -> None:
    from mcp_broker.jsonrpc import JsonRpcRequest
    from mcp_broker.protocol import McpProtocolHandler

    handler = McpProtocolHandler(server_name="mcp-broker", server_version="0.0.1")
    handler.handle(
        JsonRpcRequest.from_mapping(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            }
        )
    )

    response = handler.handle(
        JsonRpcRequest.from_mapping(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
    )

    assert response is None
    assert handler.initialized is True


def test_protocol_rejects_bad_initialize_params_and_unknown_methods() -> None:
    from mcp_broker.jsonrpc import JsonRpcRequest
    from mcp_broker.protocol import McpProtocolHandler

    handler = McpProtocolHandler(server_name="mcp-broker", server_version="0.0.1")

    missing_version = handler.handle(
        JsonRpcRequest.from_mapping(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
    )
    assert missing_version is not None
    assert missing_version.error == {
        "code": -32602,
        "message": "initialize.params.protocolVersion is required",
    }

    handler.handle(
        JsonRpcRequest.from_mapping(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            }
        )
    )
    unknown = handler.handle(
        JsonRpcRequest.from_mapping(
            {"jsonrpc": "2.0", "id": 3, "method": "unknown/method"}
        )
    )

    assert unknown is not None
    assert unknown.error == {"code": -32601, "message": "unknown method: unknown/method"}
