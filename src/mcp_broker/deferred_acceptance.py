"""Generate maintainer acceptance steps for deferred broker tools."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from mcp_broker.config import BrokerConfig
from mcp_broker.profile_validation import ProfileProbe, build_profile_validation_plan


DEFERRED_WRAPPER_NAMESPACE = "mcp__mcp_broker__"
SEARCH_WRAPPER = f"{DEFERRED_WRAPPER_NAMESPACE}.broker_search_tools"
DESCRIBE_WRAPPER = f"{DEFERRED_WRAPPER_NAMESPACE}.broker_describe_tool"
CALL_WRAPPER = f"{DEFERRED_WRAPPER_NAMESPACE}.broker_call_tool"


def build_deferred_acceptance_plan(config: BrokerConfig, profile: str) -> dict[str, Any]:
    """Return operator steps that exercise deferred MCP wrappers."""

    validation_plan = build_profile_validation_plan(config, profile)
    if validation_plan.missing_probes:
        joined = ", ".join(sorted(validation_plan.missing_probes))
        raise ValueError(f"{profile} missing smoke probes: {joined}")

    upstreams = [
        {
            "upstream": probe.upstream_name,
            "query": probe.query,
            "tool": probe.tool,
            "call_enabled": probe.call,
            "steps": _steps_for_probe(probe),
        }
        for probe in validation_plan.probes
    ]
    return {
        "profile": profile,
        "external_llm_required": True,
        "deferred_wrapper_namespace": DEFERRED_WRAPPER_NAMESPACE,
        "upstream_count": len(upstreams),
        "acceptance_scope": (
            "Run these calls from inside an active LLM client session where the mcp-broker "
            "deferred tools are available. This is not a public quality-gate input."
        ),
        "upstreams": upstreams,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Deferred Tool Acceptance",
        "",
        f"Profile: `{report['profile']}`",
        f"Upstreams: `{report['upstream_count']}`",
        "",
        str(report["acceptance_scope"]),
        "",
    ]
    for upstream in report["upstreams"]:
        lines.extend(
            [
                f"## {upstream['upstream']}",
                "",
                f"Smoke tool: `{upstream['tool']}`",
                f"Search query: `{upstream['query']}`",
                "",
            ]
        )
        for step in upstream["steps"]:
            if step.get("skipped") is True:
                lines.append(f"- `{step['step']}` skipped: {step['reason']}")
                continue
            arguments = json.dumps(step["arguments"], sort_keys=True)
            lines.append(f"- `{step['client_wrapper']}` with `{arguments}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _steps_for_probe(probe: ProfileProbe) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [
        {
            "step": "search",
            "client_wrapper": SEARCH_WRAPPER,
            "arguments": {"query": probe.query, "limit": 100},
        },
        {
            "step": "describe",
            "client_wrapper": DESCRIBE_WRAPPER,
            "arguments": {"name": probe.tool},
        },
    ]
    if probe.call:
        steps.append(
            {
                "step": "call",
                "client_wrapper": CALL_WRAPPER,
                "arguments": {"name": probe.tool, "arguments": probe.arguments},
            }
        )
    else:
        steps.append(
            {
                "step": "call",
                "skipped": True,
                "reason": "smoke.call is false",
            }
        )
    return steps


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config = BrokerConfig.from_file(Path(args.config))
        report = build_deferred_acceptance_plan(config, args.profile)
        if args.format == "markdown":
            sys.stdout.write(render_markdown(report))
        else:
            sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
        return 0
    except (ValueError, json.JSONDecodeError) as exc:
        sys.stderr.write(str(exc) + "\n")
        return 1


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate maintainer-only deferred-tool acceptance steps"
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile", default="codex")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
