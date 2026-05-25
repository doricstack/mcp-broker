"""Stateless stdio client shim for mcp-broker."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import socket
import sys
from typing import BinaryIO, Sequence
from uuid import uuid4


class ClientShimError(Exception):
    """Raised when the client shim cannot reach the broker daemon."""


@dataclass(frozen=True)
class ClientShim:
    socket_path: Path
    profile: str | None = None
    session_id: str = field(default_factory=lambda: uuid4().hex)

    def forward_payload(self, payload: bytes) -> bytes:
        if not self.socket_path.exists():
            raise ClientShimError(f"broker socket unavailable: {self.socket_path}")
        outbound = _inject_broker_metadata(payload, self.profile, self.session_id)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(self.socket_path))
                client.sendall(outbound)
                return _read_response(client)
        except OSError as exc:
            raise ClientShimError(f"broker socket unavailable: {self.socket_path}") from exc

    def run_stdio(self, stdin: BinaryIO, stdout: BinaryIO) -> None:
        for payload in stdin:
            response = self.forward_payload(payload)
            if _is_jsonrpc_notification(payload):
                continue
            stdout.write(response)
            stdout.flush()


def _read_response(client: socket.socket) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = client.recv(65536)
        if not chunk:
            break
        chunks.append(chunk)
        if chunk.endswith(b"\n"):
            break
    return b"".join(chunks)


def _inject_broker_metadata(payload: bytes, profile: str | None, session_id: str) -> bytes:
    try:
        request = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return payload
    if not isinstance(request, dict) or request.get("method") not in {"tools/list", "tools/call"}:
        return payload
    params = request.get("params")
    if params is None:
        request["params"] = _broker_metadata(profile=profile, session_id=session_id)
    elif isinstance(params, dict):
        if profile is not None and params.get("profile") is None:
            params["profile"] = profile
        if params.get("broker_session_id") is None:
            params["broker_session_id"] = session_id
        if params.get("broker_client_cwd") is None:
            params["broker_client_cwd"] = os.getcwd()
    else:
        return payload
    return json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\n"


def _broker_metadata(*, profile: str | None, session_id: str) -> dict[str, str]:
    metadata = {"broker_session_id": session_id, "broker_client_cwd": os.getcwd()}
    if profile is not None:
        metadata["profile"] = profile
    return metadata


def _is_jsonrpc_notification(payload: bytes) -> bool:
    try:
        request = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(request, dict) and request.get("jsonrpc") == "2.0" and "id" not in request


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the mcp-broker stdio client shim")
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--session-id")
    args = parser.parse_args(argv)
    try:
        ClientShim(
            socket_path=Path(os.path.expandvars(args.socket_path)).expanduser(),
            profile=args.profile,
            session_id=args.session_id or uuid4().hex,
        ).run_stdio(
            sys.stdin.buffer,
            sys.stdout.buffer,
        )
    except ClientShimError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
