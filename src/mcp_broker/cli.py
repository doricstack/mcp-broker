"""Top-level CLI for package installs."""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import shutil
import sys
from threading import Event
from typing import Callable, Sequence

from mcp_broker.client import ClientShim, ClientShimError
from mcp_broker.config import BrokerConfig
from mcp_broker.config_render import main as config_render_main
from mcp_broker.daemon import BrokerDaemon, main as daemon_main


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
    init_parser.add_argument("--template", type=Path)
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(handler=handle_init)

    start_parser = _daemon_parser(subparsers, "start", "Start the broker daemon in the foreground")
    start_parser.add_argument("--config", type=Path, default=default_config_path())
    start_parser.set_defaults(handler=handle_daemon)

    stdio_parser = _daemon_parser(
        subparsers,
        "stdio",
        "Run the broker daemon and stdio client in one process",
    )
    stdio_parser.add_argument("--config", type=Path, default=default_config_path())
    stdio_parser.add_argument("--profile", default=os.environ.get("MCP_BROKER_PROFILE"))
    stdio_parser.add_argument("--init-if-missing", action="store_true")
    stdio_parser.add_argument(
        "--ready-attempts",
        type=int,
        default=int(os.environ.get("MCP_BROKER_READY_ATTEMPTS", "50")),
    )
    stdio_parser.set_defaults(handler=handle_stdio)

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
    current_tree_template = Path.cwd() / "config" / "broker.example.yaml"
    installed_template = Path(sys.prefix) / "share" / "mcp-broker" / "config" / "broker.example.yaml"
    return template_path_from_candidates(source_tree_template, current_tree_template, installed_template)


def template_path_from_candidates(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]


def handle_init(args: argparse.Namespace) -> int:
    config_path = args.config.expanduser()
    template_path = (args.template or default_template_path()).expanduser()
    return initialize_config(config_path, template_path=template_path, force=args.force)


def initialize_config(config_path: Path, *, template_path: Path, force: bool) -> int:
    if config_path.exists() and not force:
        sys.stdout.write(f"config already exists: {config_path}\n")
        return 0
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


def stdio_argv(
    *,
    runtime_root: Path,
    socket_path: Path,
    config_path: Path,
    profile: str | None,
    init_if_missing: bool,
    ready_attempts: int | None = None,
) -> list[str]:
    argv = [
        "--runtime-root",
        str(runtime_root.expanduser()),
        "--socket-path",
        str(socket_path.expanduser()),
        "--config",
        str(config_path.expanduser()),
    ]
    if profile is not None:
        argv.extend(["--profile", profile])
    if init_if_missing:
        argv.append("--init-if-missing")
    if ready_attempts is not None:
        argv.extend(["--ready-attempts", str(ready_attempts)])
    return argv


def handle_stdio(args: argparse.Namespace) -> int:
    return stdio_main(
        stdio_argv(
            runtime_root=args.runtime_root,
            socket_path=args.socket_path,
            config_path=args.config,
            profile=args.profile,
            init_if_missing=args.init_if_missing,
            ready_attempts=args.ready_attempts,
        )
    )


def stdio_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run mcp-broker as a one-process stdio server")
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--init-if-missing", action="store_true")
    parser.add_argument("--ready-attempts", type=int, default=50)
    args = parser.parse_args(argv)

    runtime_root = Path(os.path.expandvars(args.runtime_root)).expanduser()
    socket_path = Path(os.path.expandvars(args.socket_path)).expanduser()
    config_path = Path(os.path.expandvars(args.config)).expanduser()

    if args.init_if_missing and not config_path.exists():
        initialized = initialize_config(
            config_path,
            template_path=default_template_path().expanduser(),
            force=False,
        )
        if initialized != 0:
            return initialized

    if not config_path.exists():
        sys.stderr.write(f"missing config: {config_path}\n")
        return 1

    daemon = BrokerDaemon(
        runtime_root=runtime_root,
        socket_path=socket_path,
        broker_config=BrokerConfig.from_file(config_path),
    )
    try:
        daemon.start()
        if not _wait_for_socket(socket_path, attempts=args.ready_attempts):
            sys.stderr.write(f"broker socket did not become ready: {socket_path}\n")
            return 1
        ClientShim(socket_path=socket_path, profile=args.profile).run_stdio(
            sys.stdin.buffer,
            sys.stdout.buffer,
        )
    except ClientShimError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    finally:
        daemon.stop()
    return 0


def _wait_for_socket(
    socket_path: Path,
    *,
    attempts: int,
    wait: Callable[[float], object] | None = None,
) -> bool:
    waiter = wait or Event().wait
    for attempt in range(attempts):
        if socket_path.exists():
            return True
        if attempt < attempts - 1:
            waiter(0.1)
    return False


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
