"""Top-level CLI for package installs."""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import shutil
import sys
from typing import Callable, Sequence

from mcp_broker.config_render import main as config_render_main
from mcp_broker.daemon import main as daemon_main


DaemonRunner = Callable[[Sequence[str] | None], int]
RenderRunner = Callable[[Sequence[str] | None], int]


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize, run, and inspect mcp-broker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a private config from the public example")
    init_parser.add_argument("--config", type=Path, default=default_config_path())
    init_parser.add_argument("--template", type=Path, default=None)
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(handler=handle_init)

    start_parser = _daemon_parser(subparsers, "start", "Start the broker daemon in the foreground")
    start_parser.add_argument("--config", type=Path, default=default_config_path())
    start_parser.set_defaults(handler=handle_daemon)

    status_parser = _daemon_parser(subparsers, "status", "Query broker daemon status")
    status_parser.set_defaults(handler=handle_daemon)

    stop_parser = _daemon_parser(subparsers, "stop", "Ask the broker daemon to stop")
    stop_parser.set_defaults(handler=handle_daemon)

    render_parser = subparsers.add_parser("render", help="Render one client config")
    render_parser.add_argument("client")
    render_parser.add_argument("--config", type=Path, default=default_config_path())
    render_parser.add_argument("--dry-run", action="store_true", default=True)
    render_parser.add_argument("--apply", action="store_true")
    render_parser.add_argument("--target-path", type=Path)
    render_parser.set_defaults(handler=handle_render)

    return parser


def _daemon_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    command: str,
    help_text: str,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(command, help=help_text)
    parser.add_argument("--runtime-root", type=Path, default=default_runtime_root())
    parser.add_argument("--socket-path", type=Path, default=default_socket_path())
    return parser


def default_runtime_root() -> Path:
    configured = os.environ.get("MCP_BROKER_RUNTIME_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "mcp" / "mcp-broker"


def default_socket_path() -> Path:
    configured = os.environ.get("MCP_BROKER_SOCKET")
    if configured:
        return Path(configured).expanduser()
    return default_runtime_root() / "sockets" / "broker.sock"


def default_config_path() -> Path:
    configured = os.environ.get("MCP_BROKER_CONFIG")
    if configured:
        return Path(configured).expanduser()
    return default_runtime_root() / "config" / "broker.yaml"


def default_template_path() -> Path:
    source_tree_template = Path(__file__).resolve().parents[2] / "config" / "broker.example.yaml"
    installed_template = Path(sys.prefix) / "share" / "mcp-broker" / "config" / "broker.example.yaml"
    return template_path_from_candidates(source_tree_template, installed_template)


def template_path_from_candidates(source_tree_template: Path, installed_template: Path) -> Path:
    if source_tree_template.exists():
        return source_tree_template
    return installed_template


def handle_init(args: argparse.Namespace) -> int:
    config_path = args.config.expanduser()
    if config_path.exists() and not args.force:
        sys.stdout.write(f"config already exists: {config_path}\n")
        return 0
    template_path = (args.template or default_template_path()).expanduser()
    if not template_path.exists():
        sys.stderr.write(f"missing config template: {template_path}\n")
        return 1
    config_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template_path, config_path)
    sys.stdout.write(f"created config: {config_path}\n")
    return 0


def daemon_argv(
    *,
    command: str,
    runtime_root: Path,
    socket_path: Path,
    config_path: Path | None,
) -> list[str]:
    daemon_command = "serve" if command == "start" else command
    argv = [
        daemon_command,
        "--runtime-root",
        str(runtime_root.expanduser()),
        "--socket-path",
        str(socket_path.expanduser()),
    ]
    if daemon_command == "serve" and config_path is not None:
        argv.extend(["--config", str(config_path.expanduser())])
    return argv


def handle_daemon(args: argparse.Namespace) -> int:
    return daemon_main(
        daemon_argv(
            command=args.command,
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            config_path=getattr(args, "config", None),
        )
    )


def handle_render(args: argparse.Namespace) -> int:
    argv = [
        "render",
        "--config",
        str(args.config.expanduser()),
        "--client",
        args.client,
    ]
    if args.apply:
        argv.append("--apply")
    if args.target_path is not None:
        argv.extend(["--target-path", str(args.target_path.expanduser())])
    return config_render_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
