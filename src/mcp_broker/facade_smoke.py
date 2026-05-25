"""Exercise compact broker facade through the stateless client shim."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Sequence
from uuid import uuid4

from mcp_broker.config import BrokerConfig
from mcp_broker.daemon import BrokerDaemon, BrokerDaemonError


class FacadeSmokeError(RuntimeError):
    """Raised when the facade smoke cannot prove the compact path."""


def parse_call_args(raw: str) -> dict[str, Any]:
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("call args must be a JSON object")
    return value


def build_facade_smoke_report(
    *,
    profile: str,
    list_response: dict[str, Any],
    search_response: dict[str, Any],
    describe_response: dict[str, Any],
    call_response: dict[str, Any],
    started_daemon: bool,
) -> dict[str, Any]:
    tools = list_response["result"]["tools"]
    search_payload = json.loads(search_response["result"]["content"][0]["text"])
    described_payload = json.loads(describe_response["result"]["content"][0]["text"])
    call_content = call_response["result"]["content"]
    call_text = call_content[0]["text"] if call_content else ""
    if call_response["result"].get("isError") is True or call_text.startswith("Error:"):
        raise FacadeSmokeError(f"{call_response['id']} returned upstream error: {call_text}")
    return {
        "profile": profile,
        "advertised_tools": sorted(str(tool["name"]) for tool in tools),
        "search_hit_count": len(search_payload["matches"]),
        "described_tool": described_payload["tool"]["name"],
        "called_tool": call_response["id"],
        "call_text": call_text,
        "started_daemon": started_daemon,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = _run_smoke(args)
        sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
        return 0
    except (FacadeSmokeError, ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1


def _run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    config = BrokerConfig.from_file(Path(args.config))
    started_daemon = False
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    session_id = f"facade-smoke-{uuid4().hex}"
    try:
        started_daemon = _start_daemon_if_needed(daemon)
        responses = _exercise_client_shim(
            socket_path=config.runtime.socket_path,
            profile=args.profile,
            query=args.query,
            call_tool=args.call_tool,
            call_args=parse_call_args(args.call_args),
            session_id=session_id,
        )
        return build_facade_smoke_report(
            profile=args.profile,
            list_response=responses["tools/list"],
            search_response=responses["broker.search_tools"],
            describe_response=responses["broker.describe_tool"],
            call_response=responses[args.call_tool],
            started_daemon=started_daemon,
        )
    finally:
        if not started_daemon:
            _stop_smoke_session(config.runtime.socket_path, args.profile, session_id)
        if started_daemon:
            try:
                _request_through_client(
                    socket_path=config.runtime.socket_path,
                    profile=args.profile,
                    session_id="facade-smoke-stop",
                    payload={"jsonrpc": "2.0", "id": "stop", "method": "broker/stop"},
                )
                daemon.join(timeout=5)
            finally:
                daemon.stop()


def _start_daemon_if_needed(daemon: BrokerDaemon) -> bool:
    try:
        daemon.start()
    except BrokerDaemonError as exc:
        if "broker daemon already running" not in str(exc):
            raise
        return False
    return True


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Exercise compact Codex broker facade")
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", default="codex")
    parser.add_argument("--query", required=True)
    parser.add_argument("--call-tool", required=True)
    parser.add_argument("--call-args", required=True)
    return parser.parse_args(argv)


def _exercise_client_shim(
    *,
    socket_path: Path,
    profile: str,
    query: str,
    call_tool: str,
    call_args: dict[str, Any],
    session_id: str,
) -> dict[str, dict[str, Any]]:
    initialize_response = _smoke_request(socket_path, profile, session_id, _initialize_payload())
    _raise_on_error(initialize_response)
    list_response = _smoke_request(socket_path, profile, session_id, _tools_list_payload())
    _raise_on_error(list_response)
    search_response = _smoke_request(socket_path, profile, session_id, _search_payload(query))
    _raise_on_error(search_response)
    describe_response = _smoke_request(socket_path, profile, session_id, _describe_payload(call_tool))
    _raise_on_error(describe_response)
    call_response = _smoke_request(
        socket_path,
        profile,
        session_id,
        _call_payload(call_tool, call_args),
    )
    _raise_on_error(call_response)
    return {
        "tools/list": list_response,
        "broker.search_tools": search_response,
        "broker.describe_tool": describe_response,
        call_tool: call_response,
    }


def _smoke_request(
    socket_path: Path,
    profile: str,
    session_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return _request_through_client(
        socket_path=socket_path,
        profile=profile,
        session_id=session_id,
        payload=payload,
    )


def _initialize_payload() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "initialize",
        "method": "initialize",
        "params": {"protocolVersion": "2025-11-25"},
    }


def _tools_list_payload() -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": "tools/list", "method": "tools/list"}


def _search_payload(query: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "broker.search_tools",
        "method": "tools/call",
        "params": {
            "name": "broker.search_tools",
            "arguments": {"query": query, "limit": 10},
        },
    }


def _describe_payload(call_tool: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "broker.describe_tool",
        "method": "tools/call",
        "params": {
            "name": "broker.describe_tool",
            "arguments": {"name": call_tool},
        },
    }


def _call_payload(call_tool: str, call_args: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": call_tool,
        "method": "tools/call",
        "params": {
            "name": "broker.call_tool",
            "arguments": {"name": call_tool, "arguments": call_args},
        },
    }


def _request_through_client(
    *,
    socket_path: Path,
    profile: str,
    session_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_broker.client",
            "--socket-path",
            str(socket_path),
            "--profile",
            profile,
            "--session-id",
            session_id,
        ],
        input=json.dumps(payload) + "\n",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise FacadeSmokeError(process.stderr.strip() or "client shim failed")
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise FacadeSmokeError(f"invalid client response: {process.stdout!r}") from exc


def _raise_on_error(response: dict[str, Any]) -> None:
    if "error" in response:
        raise FacadeSmokeError(json.dumps(response["error"], sort_keys=True))


def _stop_smoke_session(socket_path: Path, profile: str, session_id: str) -> None:
    try:
        _request_through_client(
            socket_path=socket_path,
            profile=profile,
            session_id=session_id,
            payload={
                "id": "broker/session/stop",
                "method": "broker/session/stop",
                "params": {"broker_session_id": session_id},
            },
        )
    except FacadeSmokeError:
        return


if __name__ == "__main__":
    raise SystemExit(main())
