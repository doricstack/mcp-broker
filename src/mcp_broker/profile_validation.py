"""Validate every enabled profile upstream through the compact broker facade."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Callable, Sequence
from uuid import uuid4

from jsonschema import Draft202012Validator, ValidationError

from mcp_broker.config import BrokerConfig
from mcp_broker.daemon import BrokerDaemon
from mcp_broker.discovery_parity import (
    DiscoveryParityError,
    _client_request,
    _status_payload,
    _tool_payload,
)
from mcp_broker.facade_smoke import (
    FacadeSmokeError,
    _call_payload,
    _describe_payload,
    _initialize_payload,
    _raise_on_error,
    _request_through_client,
    _start_daemon_if_needed,
    _stop_smoke_session,
    _tools_list_payload,
)


RequestFn = Callable[[Path, str, str, dict[str, Any]], dict[str, Any]]
HEALTHY_UPSTREAM_STATES = frozenset({"running", "reachable"})


@dataclass(frozen=True)
class ProfileProbe:
    upstream_name: str
    query: str
    tool: str
    arguments: dict[str, Any]
    call: bool = True


@dataclass(frozen=True)
class ProfileValidationPlan:
    probes: tuple[ProfileProbe, ...]
    missing_probes: list[str]


def build_profile_validation_plan(config: BrokerConfig, profile: str) -> ProfileValidationPlan:
    probes: list[ProfileProbe] = []
    missing_probes: list[str] = []
    for upstream_name in sorted(config.upstreams):
        upstream = config.upstreams[upstream_name]
        if not upstream.enabled or upstream.mode == "disabled" or profile not in upstream.profiles:
            continue
        if upstream.smoke is None:
            missing_probes.append(upstream.name)
            continue
        probes.append(
            ProfileProbe(
                upstream_name=upstream.name,
                query=upstream.smoke.query,
                tool=upstream.smoke.tool,
                arguments=upstream.smoke.arguments,
                call=upstream.smoke.call,
            )
        )
    return ProfileValidationPlan(probes=tuple(probes), missing_probes=missing_probes)


def run_profile_validation(
    *,
    socket_path: Path,
    profile: str,
    probes: Sequence[ProfileProbe | dict[str, Any]],
    missing_probes: list[str],
    session_id: str,
    request_fn: RequestFn = _client_request,
) -> dict[str, Any]:
    if missing_probes:
        joined = ", ".join(sorted(missing_probes))
        raise DiscoveryParityError(f"{profile} missing smoke probes: {joined}")

    tools, upstreams = _load_facade_state(socket_path, profile, session_id, request_fn)
    probe_results: dict[str, dict[str, Any]] = {}
    for probe in probes:
        normalized_probe = _normalize_probe(probe)
        probe_result = _run_single_probe(
            socket_path=socket_path,
            profile=profile,
            session_id=session_id,
            upstreams=upstreams,
            probe=normalized_probe,
            request_fn=request_fn,
        )
        probe_results[normalized_probe.upstream_name] = probe_result

    return {
        "matches": True,
        "profile": profile,
        "advertised_tools": sorted(str(tool["name"]) for tool in tools),
        "visible_upstreams": sorted(
            str(name)
            for name, snapshot in upstreams.items()
            if isinstance(snapshot, dict) and snapshot.get("exposed") is True
        ),
        "validated_upstreams": sorted(probe_results),
        "missing_probes": [],
        "probe_results": probe_results,
    }


def _load_facade_state(
    socket_path: Path,
    profile: str,
    session_id: str,
    request_fn: RequestFn,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    initialize_response = request_fn(socket_path, profile, session_id, _initialize_payload())
    initial_status_response = request_fn(socket_path, profile, session_id, _status_payload())

    _raise_on_error(initialize_response)
    _raise_on_error(initial_status_response)
    initial_upstreams = _upstreams_from_status(profile, initial_status_response)
    _raise_on_unhealthy_exposed_upstreams(profile, initial_upstreams)

    list_response = request_fn(socket_path, profile, session_id, _tools_list_payload())
    status_response = request_fn(socket_path, profile, session_id, _status_payload())
    _raise_on_error(list_response)
    _raise_on_error(status_response)

    tools = list_response["result"]["tools"]
    return tools, _upstreams_from_status(profile, status_response)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = _run_validation(args)
        sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
        return 0
    except (
        DiscoveryParityError,
        FacadeSmokeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1


def _run_validation(args: argparse.Namespace) -> dict[str, Any]:
    config = BrokerConfig.from_file(Path(args.config))
    plan = build_profile_validation_plan(config, args.profile)
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    session_id = f"profile-validation-{args.profile}-{uuid4().hex}"
    started_daemon = _start_daemon_if_needed(daemon)
    try:
        report = run_profile_validation(
            socket_path=config.runtime.socket_path,
            profile=args.profile,
            probes=plan.probes,
            missing_probes=plan.missing_probes,
            session_id=session_id,
        )
        return report | {"started_daemon": started_daemon}
    finally:
        if not started_daemon:
            _stop_smoke_session(config.runtime.socket_path, args.profile, session_id)
        if started_daemon:
            try:
                _request_through_client(
                    socket_path=config.runtime.socket_path,
                    profile=args.profile,
                    session_id="profile-validation-stop",
                    payload={"jsonrpc": "2.0", "id": "stop", "method": "broker/stop"},
                )
                daemon.join(timeout=5)
            finally:
                daemon.stop()


def _run_single_probe(
    *,
    socket_path: Path,
    profile: str,
    session_id: str,
    upstreams: dict[str, Any],
    probe: ProfileProbe,
    request_fn: RequestFn,
) -> dict[str, Any]:
    upstream_snapshot = _require_exposed_upstream(
        profile,
        upstreams,
        probe.upstream_name,
        context="",
        require_active=False,
    )
    matches, described_tool, input_schema = _search_and_describe_probe(
        socket_path=socket_path,
        profile=profile,
        session_id=session_id,
        probe=probe,
        request_fn=request_fn,
    )
    call_result = _call_probe_if_enabled(
        socket_path=socket_path,
        profile=profile,
        session_id=session_id,
        probe=probe,
        input_schema=input_schema,
        request_fn=request_fn,
    )
    final_upstreams = _load_upstream_status(socket_path, profile, session_id, request_fn)
    _require_exposed_upstream(
        profile,
        final_upstreams,
        probe.upstream_name,
        context="after probe",
        require_active=True,
    )

    return {
        "state": upstream_snapshot.get("state"),
        "search_matches": matches,
        "described_tool": described_tool,
        **call_result,
    }


def _require_exposed_upstream(
    profile: str,
    upstreams: dict[str, Any],
    upstream_name: str,
    *,
    context: str,
    require_active: bool,
) -> dict[str, Any]:
    upstream_snapshot = upstreams.get(upstream_name)
    if not isinstance(upstream_snapshot, dict) or upstream_snapshot.get("exposed") is not True:
        raise DiscoveryParityError(f"{profile} broker.status did not expose {upstream_name}")
    state = upstream_snapshot.get("state")
    if state in {"exited", "failed", "backoff"} or (require_active and state not in HEALTHY_UPSTREAM_STATES):
        suffix = f" {context}" if context else ""
        raise DiscoveryParityError(
            f"{profile} upstream {upstream_name} is not healthy{suffix}: state={state!r}"
        )
    if upstream_snapshot.get("last_error"):
        suffix = f" {context}" if context else ""
        raise DiscoveryParityError(
            f"{profile} upstream {upstream_name} is not healthy{suffix}: "
            f"last_error={upstream_snapshot.get('last_error')!r}"
        )
    return upstream_snapshot


def _load_upstream_status(
    socket_path: Path,
    profile: str,
    session_id: str,
    request_fn: RequestFn,
) -> dict[str, Any]:
    status_response = request_fn(socket_path, profile, session_id, _status_payload())
    _raise_on_error(status_response)
    return _upstreams_from_status(profile, status_response)


def _upstreams_from_status(profile: str, status_response: dict[str, Any]) -> dict[str, Any]:
    status_payload = _tool_payload(status_response)
    upstreams = status_payload.get("upstreams")
    if upstreams is None:
        return {}
    if not isinstance(upstreams, dict):
        raise DiscoveryParityError(f"{profile} broker.status returned invalid upstream map")
    return upstreams


def _raise_on_unhealthy_exposed_upstreams(profile: str, upstreams: dict[str, Any]) -> None:
    for upstream_name, upstream_snapshot in upstreams.items():
        if not isinstance(upstream_snapshot, dict) or upstream_snapshot.get("exposed") is not True:
            continue
        state = upstream_snapshot.get("state")
        if state in {"exited", "failed", "backoff"} or upstream_snapshot.get("last_error"):
            raise DiscoveryParityError(
                f"{profile} upstream {upstream_name} is not healthy before probe: state={state!r}"
            )


def _search_and_describe_probe(
    *,
    socket_path: Path,
    profile: str,
    session_id: str,
    probe: ProfileProbe,
    request_fn: RequestFn,
) -> tuple[list[str], str, dict[str, Any] | None]:
    search_response = request_fn(socket_path, profile, session_id, _search_probe_payload(probe.query))
    _raise_on_error(search_response)
    search_payload = _tool_payload(search_response)
    _raise_on_unavailable_probe_catalog(profile, search_payload, probe)
    matches = sorted(str(match["name"]) for match in search_payload.get("matches", []))
    if probe.tool not in matches:
        raise DiscoveryParityError(
            f"{profile} search did not return {probe.tool} for upstream {probe.upstream_name}"
        )

    describe_response = request_fn(socket_path, profile, session_id, _describe_payload(probe.tool))
    _raise_on_error(describe_response)
    describe_payload = _tool_payload(describe_response)
    described_tool = describe_payload["tool"]["name"]
    if described_tool != probe.tool:
        raise DiscoveryParityError(f"{profile} describe returned {described_tool}, expected {probe.tool}")
    input_schema = describe_payload["tool"].get("inputSchema")
    if probe.call and not isinstance(input_schema, dict):
        raise DiscoveryParityError(f"{profile} describe returned invalid inputSchema for {probe.tool}")
    return matches, described_tool, input_schema if isinstance(input_schema, dict) else None


def _raise_on_unavailable_probe_catalog(
    profile: str,
    search_payload: dict[str, Any],
    probe: ProfileProbe,
) -> None:
    skipped_upstreams = search_payload.get("skipped_upstreams")
    if skipped_upstreams is None:
        skipped_upstreams = {}
    if not isinstance(skipped_upstreams, dict):
        raise DiscoveryParityError(f"{profile} search returned invalid skipped_upstreams for {probe.upstream_name}")
    if probe.upstream_name in skipped_upstreams:
        raise DiscoveryParityError(
            f"{profile} search skipped {probe.upstream_name}: "
            f"{skipped_upstreams[probe.upstream_name]}"
        )
    matches = search_payload.get("matches", [])
    if not isinstance(matches, list):
        raise DiscoveryParityError(f"{profile} search returned invalid matches for {probe.upstream_name}")
    for match in matches:
        if (
            isinstance(match, dict)
            and match.get("upstream") == probe.upstream_name
            and match.get("available") is False
        ):
            raise DiscoveryParityError(f"{profile} search marked {probe.upstream_name} unavailable")


def _call_probe_if_enabled(
    *,
    socket_path: Path,
    profile: str,
    session_id: str,
    probe: ProfileProbe,
    input_schema: dict[str, Any] | None,
    request_fn: RequestFn,
) -> dict[str, Any]:
    call_output_bytes = 0
    call_content_items = 0
    called = probe.call
    if called:
        arguments = probe.arguments
        if not isinstance(arguments, dict):
            raise DiscoveryParityError(f"{profile} probe arguments must be a mapping: {probe.tool}")
        _validate_probe_arguments(profile, probe, input_schema, arguments)
        call_response = request_fn(
            socket_path,
            profile,
            session_id,
            _call_payload(probe.tool, arguments),
        )
        _raise_on_error(call_response)
        call_result = call_response["result"]
        call_content = call_result.get("content", [])
        call_content_items = len(call_content)
        call_text = call_content[0]["text"] if call_content else ""
        call_output_bytes = sum(len(str(item.get("text", ""))) for item in call_content)
        if call_result.get("isError") is True or call_text.startswith("Error:"):
            raise DiscoveryParityError(f"{profile} probe returned upstream error: {call_text}")

    return {
        "called": called,
        "call_content_items": call_content_items,
        "call_output_bytes": call_output_bytes,
    }


def _validate_probe_arguments(
    profile: str,
    probe: ProfileProbe,
    input_schema: dict[str, Any],
    arguments: dict[str, Any],
) -> None:
    try:
        Draft202012Validator.check_schema(input_schema)
        Draft202012Validator(input_schema).validate(arguments)
    except ValidationError as exc:
        raise DiscoveryParityError(f"{profile} probe arguments do not match schema for {probe.tool}: {exc.message}") from exc


def _normalize_probe(probe: ProfileProbe | dict[str, Any]) -> ProfileProbe:
    if isinstance(probe, ProfileProbe):
        return probe
    arguments = probe.get("arguments", {})
    return ProfileProbe(
        upstream_name=str(probe["upstream_name"]),
        query=str(probe["query"]),
        tool=str(probe["tool"]),
        arguments=arguments,
        call=bool(probe.get("call", True)),
    )


def _search_probe_payload(query: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": "broker.search_tools",
        "method": "tools/call",
        "params": {
            "name": "broker.search_tools",
            "arguments": {"query": query, "limit": 100},
        },
    }


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate all enabled profile upstreams with YAML smoke probes"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", default="codex")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
