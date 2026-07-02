"""Dry-run service manager plans for broker bootstrap."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import sys
from typing import Sequence


LAUNCHAGENT_LABEL = "com.mcp-broker.agent"
SYSTEMD_SERVICE_NAME = "mcp-broker.service"
WINDOWS_TASK_NAME = "mcp-broker"


class ServiceTemplateError(ValueError):
    """Raised when a service plan cannot be generated."""


def build_service_plan(
    *,
    platform: str,
    runtime_root: Path,
    socket_path: Path,
    config_path: Path,
    daemon_command: str,
    home_dir: Path,
) -> dict[str, object]:
    normalized_platform = platform.strip().lower()
    if not daemon_command.strip():
        raise ServiceTemplateError("daemon command is required")
    runtime_root = runtime_root.expanduser()
    socket_path = socket_path.expanduser()
    config_path = config_path.expanduser()
    home_dir = home_dir.expanduser()
    try:
        daemon_args = shlex.split(daemon_command)
    except ValueError as exc:
        raise ServiceTemplateError(f"invalid daemon command: {exc}") from exc
    command_args = [
        *daemon_args,
        "serve",
        "--runtime-root",
        str(runtime_root),
        "--socket-path",
        str(socket_path),
        "--config",
        str(config_path),
    ]
    base_plan = {
        "platform": normalized_platform,
        "dry_run": True,
        "would_mutate": False,
        "approval_required_for_apply": True,
        "runtime_root": str(runtime_root),
        "socket_path": str(socket_path),
        "config_path": str(config_path),
        "command": shlex.join(command_args),
        "command_args": command_args,
        "environment": {
            "MCP_BROKER_RUNTIME_ROOT": str(runtime_root),
            "MCP_BROKER_SOCKET": str(socket_path),
            "MCP_BROKER_CONFIG": str(config_path),
        },
    }
    if normalized_platform == "macos":
        return {
            **base_plan,
            "service_manager": "launchd",
            "service_name": LAUNCHAGENT_LABEL,
            "target_path": str(home_dir / "Library" / "LaunchAgents" / f"{LAUNCHAGENT_LABEL}.plist"),
            "render_path": str(runtime_root / "renders" / f"{LAUNCHAGENT_LABEL}.plist"),
            "load_command": f"launchctl bootstrap gui/$(id -u) {LAUNCHAGENT_LABEL}.plist",
            "unload_command": f"launchctl bootout gui/$(id -u) {LAUNCHAGENT_LABEL}.plist",
        }
    if normalized_platform == "linux":
        return {
            **base_plan,
            "service_manager": "systemd-user",
            "service_name": SYSTEMD_SERVICE_NAME,
            "target_path": str(home_dir / ".config" / "systemd" / "user" / SYSTEMD_SERVICE_NAME),
            "render_path": str(runtime_root / "renders" / SYSTEMD_SERVICE_NAME),
            "load_command": f"systemctl --user enable --now {SYSTEMD_SERVICE_NAME}",
            "unload_command": f"systemctl --user disable --now {SYSTEMD_SERVICE_NAME}",
        }
    if normalized_platform == "windows":
        return {
            **base_plan,
            "service_manager": "windows-scheduled-task",
            "service_name": WINDOWS_TASK_NAME,
            "target_path": rf"Task Scheduler\{WINDOWS_TASK_NAME}",
            "render_path": str(runtime_root / "renders" / f"windows-task-{WINDOWS_TASK_NAME}.txt"),
            "load_command": f"Register-ScheduledTask -TaskName {WINDOWS_TASK_NAME}",
            "unload_command": f"Unregister-ScheduledTask -TaskName {WINDOWS_TASK_NAME} -Confirm:$false",
        }
    raise ServiceTemplateError(f"unsupported service platform: {platform}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a dry-run service manager plan")
    parser.add_argument("--platform", required=True)
    parser.add_argument("--runtime-root", required=True, type=Path)
    parser.add_argument("--socket-path", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--daemon-command", required=True)
    parser.add_argument("--home-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        plan = build_service_plan(
            platform=args.platform,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            config_path=args.config,
            daemon_command=args.daemon_command,
            home_dir=args.home_dir,
        )
    except ServiceTemplateError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write(json.dumps(plan, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
