"""Count broker-advertised MCP tools for a profile."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import socket
import sys
from typing import Any, Sequence

from mcp_broker.config import BrokerConfig
from mcp_broker.daemon import BrokerDaemon, BrokerDaemonError


def build_tool_count_report(*, profile: str, tools: list[dict[str, Any]]) -> dict[str, Any]:
    tool_names = [str(tool["name"]) for tool in tools]
    upstream_counts = Counter(name.split(".", 1)[0] for name in tool_names)
    return {
        "profile": profile,
        "total_tools": len(tool_names),
        "upstream_counts": dict(sorted(upstream_counts.items())),
        "tools": sorted(tool_names),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    config = BrokerConfig.from_file(Path(args.config))
    response = _list_profile_tools(config=config, profile=args.profile)
    if "error" in response:
        sys.stderr.write(json.dumps(response["error"], sort_keys=True) + "\n")
        return 1
    report = build_tool_count_report(
        profile=args.profile,
        tools=response["result"]["tools"],
    )
    sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Count broker-advertised MCP tools")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", default="codex")
    return parser.parse_args(argv)


def _list_profile_tools(
    *,
    config: BrokerConfig,
    profile: str,
) -> dict[str, Any]:
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    started_daemon = False
    try:
        daemon.start()
        started_daemon = True
    except BrokerDaemonError as exc:
        if "broker daemon already running" not in str(exc):
            raise
    try:
        _request(
            config.runtime.socket_path,
            {
                "jsonrpc": "2.0",
                "id": "initialize",
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
        )
        response = _request(
            config.runtime.socket_path,
            {
                "jsonrpc": "2.0",
                "id": "tools-count",
                "method": "tools/list",
                "params": {"profile": profile},
            },
        )
        return response
    finally:
        if started_daemon:
            try:
                _request(
                    config.runtime.socket_path,
                    {"jsonrpc": "2.0", "id": "stop", "method": "broker/stop"},
                )
                daemon.join(timeout=5)
            finally:
                daemon.stop()


def _request(socket_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(30)
        client.connect(str(socket_path))
        client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        data = b""
        while not data.endswith(b"\n"):
            chunk = client.recv(65536)
            if not chunk:
                break
            data += chunk
    return json.loads(data.decode("utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
