"""Compare compact broker discovery across two client profiles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Callable, Sequence
from uuid import uuid4

from mcp_broker.config import BrokerConfig
from mcp_broker.daemon import BrokerDaemon
from mcp_broker.facade_smoke import (
    FacadeSmokeError,
    _call_payload,
    _describe_payload,
    _initialize_payload,
    _raise_on_error,
    _request_through_client,
    _search_payload,
    _start_daemon_if_needed,
    _stop_smoke_session,
    _tools_list_payload,
    parse_call_args,
)


class DiscoveryParityError(RuntimeError):
    """Raised when profile discovery parity cannot be proven."""


RequestFn = Callable[[Path, str, str, dict[str, Any]], dict[str, Any]]
TransportFn = Callable[..., dict[str, Any]]


def run_profile_discovery(
    *,
    socket_path: Path,
    profile: str,
    query: str,
    call_tool: str,
    call_args: dict[str, Any],
    session_id: str,
    request_fn: RequestFn | None = None,
) -> dict[str, Any]:
    active_request_fn = request_fn or _client_request
    responses = _profile_discovery_responses(
        socket_path,
        profile,
        session_id,
        query,
        call_tool,
        call_args,
        active_request_fn,
    )
    tools = responses["list"]["result"]["tools"]
    status_payload = _tool_payload(responses["status"])
    search_payload = _tool_payload(responses["search"])
    describe_payload = _tool_payload(responses["describe"])
    call_result = responses["call"]["result"]
    call_content = call_result.get("content", [])
    call_text = call_content[0]["text"] if call_content else ""
    if call_result.get("isError") is True or call_text.startswith("Error:"):
        raise DiscoveryParityError(f"{profile} safe call returned upstream error: {call_text}")

    upstreams = status_payload.get("upstreams", {})
    if not isinstance(upstreams, dict):
        raise DiscoveryParityError(f"{profile} broker.status returned invalid upstream map")

    return _profile_discovery_report(
        profile=profile,
        tools=tools,
        upstreams=upstreams,
        search_payload=search_payload,
        describe_payload=describe_payload,
        call_text=call_text,
    )


def _profile_discovery_report(
    *,
    profile: str,
    tools: list[dict[str, Any]],
    upstreams: dict[str, Any],
    search_payload: dict[str, Any],
    describe_payload: dict[str, Any],
    call_text: str,
) -> dict[str, Any]:
    return {
        "profile": profile,
        "advertised_tools": sorted(str(tool["name"]) for tool in tools),
        "visible_upstreams": sorted(
            str(name)
            for name, snapshot in upstreams.items()
            if isinstance(snapshot, dict) and snapshot.get("exposed") is True
        ),
        "search_matches": sorted(str(match["name"]) for match in search_payload["matches"]),
        "described_tool": describe_payload["tool"]["name"],
        "call_text": call_text,
    }


def _profile_discovery_responses(
    socket_path: Path,
    profile: str,
    session_id: str,
    query: str,
    call_tool: str,
    call_args: dict[str, Any],
    request_fn: RequestFn,
) -> dict[str, dict[str, Any]]:
    responses = {
        "initialize": request_fn(socket_path, profile, session_id, _initialize_payload()),
        "list": request_fn(socket_path, profile, session_id, _tools_list_payload()),
        "status": request_fn(socket_path, profile, session_id, _status_payload()),
        "search": request_fn(socket_path, profile, session_id, _search_payload(query)),
        "describe": request_fn(socket_path, profile, session_id, _describe_payload(call_tool)),
        "call": request_fn(socket_path, profile, session_id, _call_payload(call_tool, call_args)),
    }
    for response in responses.values():
        _raise_on_error(response)
    return responses


def compare_profile_discovery(
    left: dict[str, Any],
    right: dict[str, Any],
) -> list[str]:
    mismatches = []
    left_profile = str(left["profile"])
    right_profile = str(right["profile"])
    for key in [
        "advertised_tools",
        "visible_upstreams",
        "search_matches",
        "described_tool",
        "call_text",
    ]:
        left_value = _normalized_value(left[key])
        right_value = _normalized_value(right[key])
        if left_value == right_value:
            continue
        mismatches.append(
            f"{key} mismatch: {left_profile}={left_value!r} {right_profile}={right_value!r}"
        )
    return mismatches


def build_parity_report(
    *,
    left: dict[str, Any],
    right: dict[str, Any],
    started_daemon: bool,
) -> dict[str, Any]:
    mismatches = compare_profile_discovery(left, right)
    return {
        "matches": not mismatches,
        "mismatches": mismatches,
        "profiles": {
            str(left["profile"]): left,
            str(right["profile"]): right,
        },
        "started_daemon": started_daemon,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = _run_parity(args)
        sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
        return 0 if report["matches"] else 1
    except (
        DiscoveryParityError,
        FacadeSmokeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1


def _run_parity(args: argparse.Namespace) -> dict[str, Any]:
    config = BrokerConfig.from_file(Path(args.config))
    started_daemon = False
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    left_session_id = f"discovery-parity-{args.left_profile}-{uuid4().hex}"
    right_session_id = f"discovery-parity-{args.right_profile}-{uuid4().hex}"
    try:
        started_daemon = _start_daemon_if_needed(daemon)
        call_args = parse_call_args(args.call_args)
        left = run_profile_discovery(
            socket_path=config.runtime.socket_path,
            profile=args.left_profile,
            query=args.query,
            call_tool=args.call_tool,
            call_args=call_args,
            session_id=left_session_id,
        )
        right = run_profile_discovery(
            socket_path=config.runtime.socket_path,
            profile=args.right_profile,
            query=args.query,
            call_tool=args.call_tool,
            call_args=call_args,
            session_id=right_session_id,
        )
        return build_parity_report(left=left, right=right, started_daemon=started_daemon)
    finally:
        _cleanup_parity_daemon(config, args, daemon, started_daemon, left_session_id, right_session_id)


def _cleanup_parity_daemon(
    config: BrokerConfig,
    args: argparse.Namespace,
    daemon: BrokerDaemon,
    started_daemon: bool,
    left_session_id: str,
    right_session_id: str,
) -> None:
    if not started_daemon:
        _stop_smoke_session(config.runtime.socket_path, args.left_profile, left_session_id)
        _stop_smoke_session(config.runtime.socket_path, args.right_profile, right_session_id)
        return
    try:
        _request_through_client(
            socket_path=config.runtime.socket_path,
            profile=args.left_profile,
            session_id="discovery-parity-stop",
            payload={"jsonrpc": "2.0", "id": "stop", "method": "broker/stop"},
        )
        daemon.join(timeout=5)
    finally:
        daemon.stop()


def _client_request(
    socket_path: Path,
    profile: str,
    session_id: str,
    payload: dict[str, Any],
    transport_fn: TransportFn = _request_through_client,
) -> dict[str, Any]:
    return transport_fn(
        socket_path=socket_path,
        profile=profile,
        session_id=session_id,
        payload=payload,
    )


def _status_payload() -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "broker.status",
        "method": "tools/call",
        "params": {
            "name": "broker.status",
            "arguments": {},
        },
    }


def _tool_payload(response: dict[str, Any]) -> dict[str, Any]:
    result = response["result"]
    structured_content = result.get("structuredContent")
    if isinstance(structured_content, dict):
        return structured_content
    return json.loads(result["content"][0]["text"])


def _normalized_value(value: Any) -> Any:
    if isinstance(value, list):
        return sorted(value)
    return value


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare broker discovery across profiles")
    parser.add_argument("--config", required=True)
    parser.add_argument("--left-profile", default="codex")
    parser.add_argument("--right-profile", default="claude")
    parser.add_argument("--query", required=True)
    parser.add_argument("--call-tool", required=True)
    parser.add_argument("--call-args", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
