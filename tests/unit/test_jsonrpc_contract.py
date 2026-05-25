import json

import pytest


pytestmark = pytest.mark.unit


def test_jsonrpc_parses_request_and_notification() -> None:
    from mcp_broker.jsonrpc import JsonRpcRequest

    request = JsonRpcRequest.from_json(
        '{"jsonrpc":"2.0","id":7,"method":"tools/list","params":{"cursor":"abc"}}'
    )

    assert request.id == 7
    assert request.method == "tools/list"
    assert request.params == {"cursor": "abc"}
    assert request.is_notification is False

    notification = JsonRpcRequest.from_json(
        '{"jsonrpc":"2.0","method":"notifications/initialized"}'
    )

    assert notification.id is None
    assert notification.is_notification is True


def test_jsonrpc_serializes_result_error_and_notification_drop() -> None:
    from mcp_broker.jsonrpc import JsonRpcResponse

    assert json.loads(JsonRpcResponse.result(7, {"tools": []}).to_json()) == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"tools": []},
    }
    assert json.loads(JsonRpcResponse.error(7, -32601, "unknown method").to_json()) == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {"code": -32601, "message": "unknown method"},
    }


def test_jsonrpc_rejects_batch_invalid_json_and_bad_envelopes() -> None:
    from mcp_broker.jsonrpc import JsonRpcRequest

    with pytest.raises(ValueError, match="invalid json-rpc payload"):
        JsonRpcRequest.from_json("{")

    with pytest.raises(ValueError, match="json-rpc batches are not supported"):
        JsonRpcRequest.from_json("[]")

    with pytest.raises(ValueError, match="json-rpc payload must be an object"):
        JsonRpcRequest.from_json('"bad"')

    with pytest.raises(ValueError, match="jsonrpc must be 2.0"):
        JsonRpcRequest.from_json('{"jsonrpc":"1.0","id":1,"method":"x"}')

    with pytest.raises(ValueError, match="method is required"):
        JsonRpcRequest.from_json('{"jsonrpc":"2.0","id":1}')

    with pytest.raises(ValueError, match="params must be object or array"):
        JsonRpcRequest.from_json('{"jsonrpc":"2.0","id":1,"method":"x","params":"bad"}')
