"""Generate config snippets for adding client profiles."""

from __future__ import annotations

import argparse
import re
import sys
from typing import Sequence

from mcp_broker.client_config import SUPPORTED_CLIENT_FORMATS
from mcp_broker.profiles import BROKER_TOOL_NAME_STYLES


PROFILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def profile_snippet_text(
    *,
    profile_name: str,
    client_format: str,
    config_path: str,
    entry_name: str | None = None,
    command: str | None = None,
    broker_tool_name_style: str | None = None,
) -> str:
    resolved_entry_name = entry_name or "mcp-broker"
    resolved_command = command or "mcp-broker-client"
    resolved_broker_tool_name_style = broker_tool_name_style or "dotted"
    _validate_profile_name(profile_name)
    _validate_client_format(client_format)
    _validate_broker_tool_name_style(resolved_broker_tool_name_style)
    if not config_path:
        raise ValueError("config path must not be empty")
    lines = [
        "# Add this under profiles:",
        "profiles:",
        f"  {profile_name}:",
        "    max_tools: 80",
        "    compact_tools_enabled: true",
        f"    broker_tool_name_style: {resolved_broker_tool_name_style}",
        "",
        "# Add this under clients:",
        "clients:",
        f"  {profile_name}:",
        f"    format: {client_format}",
        f"    config_path: {config_path}",
        f"    entry_name: {resolved_entry_name}",
        f"    command: {resolved_command}",
    ]
    if client_format == "mcp-settings-json":
        lines.extend(
            [
                "    mcp_allowed_servers:",
                f"      - {resolved_entry_name}",
            ]
        )
    lines.extend(
        [
            "    args:",
            "      - --socket-path",
            "      - \"{runtime.socket_path}\"",
            "      - --profile",
            f"      - {profile_name}",
            "",
            "# Add this profile name to each upstream that should be visible:",
            "upstreams:",
            "  example-upstream:",
            "    profiles:",
            f"      - {profile_name}",
            "",
            "# Then run:",
            f"make config-render CLIENT={profile_name} CONFIG_RENDER_APPLY=0",
            f"make profile-validation PROFILE={profile_name}",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print a profile and client config snippet")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--client-format", required=True)
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--entry-name")
    parser.add_argument("--command")
    parser.add_argument("--broker-tool-name-style")
    args = parser.parse_args(argv)
    try:
        text = profile_snippet_text(
            profile_name=args.profile,
            client_format=args.client_format,
            config_path=args.config_path,
            entry_name=args.entry_name,
            command=args.command,
            broker_tool_name_style=args.broker_tool_name_style,
        )
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    sys.stdout.write(text)
    return 0


def _validate_profile_name(profile_name: str) -> None:
    if not PROFILE_NAME_PATTERN.match(profile_name):
        raise ValueError("profile name must contain only letters, numbers, underscore, or hyphen")


def _validate_client_format(client_format: str) -> None:
    if client_format not in SUPPORTED_CLIENT_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_CLIENT_FORMATS))
        raise ValueError(f"client format must be one of: {supported}")


def _validate_broker_tool_name_style(style: str) -> None:
    if style not in BROKER_TOOL_NAME_STYLES:
        supported = ", ".join(sorted(BROKER_TOOL_NAME_STYLES))
        raise ValueError(f"broker tool name style must be one of: {supported}")


if __name__ == "__main__":
    raise SystemExit(main())
