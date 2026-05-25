"""Small stdio MCP server used by e2e tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def main() -> int:
    state_dir = Path(os.environ["MCP_BROKER_UPSTREAM_STATE_DIR"])
    state_dir.mkdir(parents=True, exist_ok=True)
    log_path = state_dir / "requests.log"

    for line in sys.stdin:
        payload = json.loads(line)
        method = str(payload.get("method", ""))
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(method + "\n")
        response = _response(payload, method)
        if response is None:
            continue
        sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
        sys.stdout.flush()
    return 0


def _response(payload: dict[str, object], method: str) -> dict[str, object] | None:
    if "id" not in payload:
        return None
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "protocolVersion": "2025-11-25",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "sample-mcp-server", "version": "0.0.1"},
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo a text message.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"message": {"type": "string"}},
                            "required": ["message"],
                        },
                    }
                ]
            },
        }
    if method == "tools/call":
        params = payload.get("params", {})
        if not isinstance(params, dict):
            params = {}
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        return {
            "jsonrpc": "2.0",
            "id": payload["id"],
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": str(arguments.get("message", "")),
                    }
                ]
            },
        }
    return {
        "jsonrpc": "2.0",
        "id": payload["id"],
        "error": {"code": -32601, "message": f"unknown method: {method}"},
    }


if __name__ == "__main__":
    raise SystemExit(main())
