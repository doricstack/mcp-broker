"""Command-line plumbing for the mcp-broker daemon."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
from typing import Sequence

from mcp_broker.config import BrokerConfig
from mcp_broker.daemon import BrokerDaemon


def main(
    argv: Sequence[str] | None = None,
    *,
    daemon_cls: type[BrokerDaemon] = BrokerDaemon,
    request_fn: object | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Run and inspect mcp-broker daemon")
    parser.add_argument("command", choices=("serve", "status", "stop"))
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--config")
    args = parser.parse_args(argv)
    runtime_root = Path(args.runtime_root)
    socket_path = Path(args.socket_path)
    if args.command == "serve":
        daemon_cls(
            runtime_root=runtime_root,
            socket_path=socket_path,
            broker_config=_broker_config_for_serve(args.config),
        ).serve_forever()
        return 0
    active_request = request_fn if callable(request_fn) else _client_request
    response = active_request(socket_path, _broker_method_for_command(args.command))
    sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
    return 0


def _broker_config_for_serve(config_path: str | Path | None) -> BrokerConfig | None:
    if config_path is None:
        return None
    return BrokerConfig.from_file(Path(config_path))


def _broker_method_for_command(command: str) -> str:
    if command == "status":
        return "broker/health"
    return f"broker/{command}"


def _client_request(socket_path: Path, method: str) -> dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall(json.dumps({"id": method, "method": method}).encode() + b"\n")
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        return json.loads(b"".join(chunks).decode())
