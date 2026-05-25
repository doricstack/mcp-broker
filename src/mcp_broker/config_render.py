"""Safe client config rendering for mcp-broker shims."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Sequence

from mcp_broker.codex_app_policy import CodexAppPolicyResult, apply_codex_app_policy
from mcp_broker.config import BrokerConfig, ClientRenderConfig


_LEGACY_CODEX_MCP_COMMENT_MARKERS = (
    "# === MCP servers (synced from ~/mcp/servers.json + project .mcp.json files) ===",
    "#   GLOBAL SERVERS (all projects)",
)


@dataclass(frozen=True)
class RenderResult:
    client_name: str
    target_path: Path
    rendered_path: Path
    backup_path: Path | None
    dry_run: bool
    codex_apps_policy_result: CodexAppPolicyResult | None = None


@dataclass(frozen=True)
class RollbackResult:
    client_name: str
    target_path: Path
    restored_path: Path


@dataclass(frozen=True)
class BackupResult:
    client_name: str
    backup_paths: tuple[Path, ...]


@dataclass(frozen=True)
class AppPolicyApplyResult:
    client_name: str
    codex_apps_policy_result: CodexAppPolicyResult


def render_client_config(
    config: BrokerConfig,
    *,
    client_name: str,
    dry_run: bool,
    backup_label: str | None = None,
    target_path: Path | None = None,
) -> RenderResult:
    client = _client(config, client_name)
    rendered_path = _rendered_path(config, client)
    rendered_path.parent.mkdir(parents=True, exist_ok=True)
    write_path = target_path or client.config_path
    rendered_text = _render_text(config, client, target_path=write_path)
    rendered_path.write_text(rendered_text, encoding="utf-8")
    backup_path = None
    if not dry_run:
        backup_path = _backup_target(config, client, backup_label=backup_label, target_path=write_path)
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_text(rendered_text, encoding="utf-8")
    policy_result = _apply_codex_apps_policy(
        config,
        client,
        backup_label=backup_label,
        dry_run=dry_run,
    )
    return RenderResult(
        client_name=client_name,
        target_path=write_path,
        rendered_path=rendered_path,
        backup_path=backup_path,
        dry_run=dry_run,
        codex_apps_policy_result=policy_result,
    )


def backup_client_config(
    config: BrokerConfig,
    *,
    client_name: str,
    backup_label: str | None = None,
) -> BackupResult:
    client = _client(config, client_name)
    backup_paths = [
        _backup_path(config, client.name, client.config_path, backup_label=backup_label)
    ]
    backup_paths.extend(
        _backup_path(config, client.name, path, backup_label=backup_label)
        for path in client.backup_paths
    )
    return BackupResult(client_name=client_name, backup_paths=tuple(backup_paths))


def rollback_client_config(
    config: BrokerConfig,
    *,
    client_name: str,
) -> RollbackResult:
    client = _client(config, client_name)
    backup_path = _latest_backup(config, client)
    client.config_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(backup_path, client.config_path)
    return RollbackResult(
        client_name=client_name,
        target_path=client.config_path,
        restored_path=backup_path,
    )


def apply_client_app_policy(
    config: BrokerConfig,
    *,
    client_name: str,
    dry_run: bool,
    backup_label: str | None = None,
) -> AppPolicyApplyResult:
    client = _client(config, client_name)
    return AppPolicyApplyResult(
        client_name=client_name,
        codex_apps_policy_result=_apply_codex_apps_policy(
            config,
            client,
            backup_label=backup_label,
            dry_run=dry_run,
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render or roll back MCP client configs")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_subcommands(subparsers)
    args = parser.parse_args(argv)
    config = BrokerConfig.from_file(Path(args.config))
    result = _run_command(args, config)
    sys.stdout.write(_json_line(result))
    return 0


def _add_subcommands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--config", required=True)
    backup_parser.add_argument("--client", required=True)
    backup_parser.add_argument("--label")
    render_parser = subparsers.add_parser("render")
    render_parser.add_argument("--config", required=True)
    render_parser.add_argument("--client", required=True)
    render_parser.add_argument("--apply", action="store_true")
    render_parser.add_argument("--target-path")
    app_policy_parser = subparsers.add_parser("app-policy")
    app_policy_parser.add_argument("--config", required=True)
    app_policy_parser.add_argument("--client", required=True)
    app_policy_parser.add_argument("--apply", action="store_true")
    app_policy_parser.add_argument("--label")
    rollback_parser = subparsers.add_parser("rollback")
    rollback_parser.add_argument("--config", required=True)
    rollback_parser.add_argument("--client", required=True)


def _run_command(args: argparse.Namespace, config: BrokerConfig) -> object:
    if args.command == "backup":
        return backup_client_config(
            config,
            client_name=args.client,
            backup_label=args.label,
        )
    if args.command == "render":
        return render_client_config(
            config,
            client_name=args.client,
            dry_run=not args.apply,
            target_path=Path(args.target_path) if args.target_path else None,
        )
    if args.command == "app-policy":
        return apply_client_app_policy(
            config,
            client_name=args.client,
            dry_run=not args.apply,
            backup_label=args.label,
        )
    return rollback_client_config(config, client_name=args.client)


def _client(config: BrokerConfig, client_name: str) -> ClientRenderConfig:
    try:
        return config.clients[client_name]
    except KeyError as exc:
        raise ValueError(f"unknown client config: {client_name}") from exc


def _rendered_path(config: BrokerConfig, client: ClientRenderConfig) -> Path:
    suffix = ".toml" if client.format == "codex-toml" else ".json"
    return config.runtime.root / "renders" / f"{client.name}.config{suffix}"


def _render_text(config: BrokerConfig, client: ClientRenderConfig, *, target_path: Path | None = None) -> str:
    args = list(client.args) or ["--socket-path", str(config.runtime.socket_path)]
    args = [_portable_client_arg(arg) for arg in args]
    source_path = target_path or client.config_path
    existing_text = source_path.read_text(encoding="utf-8") if source_path.exists() else ""
    if client.format == "codex-toml":
        return _render_codex_toml(client.entry_name, client.command, args, existing_text)
    if client.format == "claude-json":
        return _render_claude_json(client.entry_name, client.command, args, existing_text)
    raise ValueError(f"unsupported client config format: {client.format}")


def _portable_client_arg(arg: str) -> str:
    home = Path(os.path.expanduser("~"))
    if not home.is_absolute() or str(home) == "/":
        return arg
    try:
        relative = Path(arg).relative_to(home)
    except ValueError:
        return arg
    if str(relative) == ".":
        return "$HOME"
    return f"$HOME/{relative}"


def _render_codex_toml(entry_name: str, command: str, args: list[str], existing_text: str) -> str:
    escaped_args = ", ".join(_quote_toml(arg) for arg in args)
    broker_entry = (
        f'[mcp_servers."{_escape_toml_string(entry_name)}"]\n'
        f'command = "{_escape_toml_string(command)}"\n'
        f"args = [{escaped_args}]\n"
    )
    preserved = _strip_trailing_separator_comments(_strip_codex_mcp_tables(existing_text))
    if not preserved.strip():
        return broker_entry
    return f"{preserved.rstrip()}\n\n{broker_entry}"


def _strip_codex_mcp_tables(existing_text: str) -> str:
    kept_lines: list[str] = []
    skip_table = False
    skip_legacy_comment_block = False
    pending_separator_lines: list[str] = []
    for line in existing_text.splitlines():
        stripped = line.strip()
        if skip_legacy_comment_block:
            if stripped.startswith("[") and stripped.endswith("]"):
                skip_legacy_comment_block = False
            else:
                continue
        if stripped == "# -----------------------------------------------------------------------------":
            pending_separator_lines = [line]
            continue
        if pending_separator_lines and not stripped:
            pending_separator_lines.append(line)
            continue
        if stripped in _LEGACY_CODEX_MCP_COMMENT_MARKERS:
            pending_separator_lines = []
            skip_legacy_comment_block = True
            continue
        elif pending_separator_lines:
            kept_lines.extend(pending_separator_lines)
            pending_separator_lines = []
        if stripped.startswith("[") and stripped.endswith("]"):
            skip_table = _is_codex_mcp_table(stripped)
        if not skip_table and not skip_legacy_comment_block:
            kept_lines.append(line)
    kept_lines.extend(pending_separator_lines)
    return "\n".join(kept_lines).rstrip() + "\n" if kept_lines else ""


def _is_codex_mcp_table(table_header: str) -> bool:
    table_name = table_header.strip("[]").strip()
    return table_name == "mcp_servers" or table_name.startswith("mcp_servers.")


def _strip_trailing_separator_comments(text: str) -> str:
    lines = text.splitlines()
    while lines and lines[-1].strip() == "# -----------------------------------------------------------------------------":
        lines.pop()
        while lines and not lines[-1].strip():
            lines.pop()
    return "\n".join(lines).rstrip() + "\n" if lines else ""


def _render_claude_json(entry_name: str, command: str, args: list[str], existing_text: str) -> str:
    preserved = json.loads(existing_text) if existing_text.strip() else {}
    if not isinstance(preserved, dict):
        preserved = {}
    preserved["mcpServers"] = {
        entry_name: {
            "command": command,
            "args": args,
        }
    }
    return (
        json.dumps(
            preserved,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def _backup_target(
    config: BrokerConfig,
    client: ClientRenderConfig,
    *,
    backup_label: str | None,
    target_path: Path | None = None,
) -> Path:
    return _backup_path(config, client.name, target_path or client.config_path, backup_label=backup_label)


def _apply_codex_apps_policy(
    config: BrokerConfig,
    client: ClientRenderConfig,
    *,
    backup_label: str | None,
    dry_run: bool,
) -> CodexAppPolicyResult | None:
    if client.codex_apps_policy is None:
        return None
    return apply_codex_app_policy(
        client.codex_apps_policy,
        backup_dir=config.runtime.root / "backups" / client.name / "codex-apps",
        backup_label=backup_label or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        dry_run=dry_run,
    )


def _backup_path(
    config: BrokerConfig,
    client_name: str,
    source_path: Path,
    *,
    backup_label: str | None,
) -> Path:
    label = backup_label or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = config.runtime.root / "backups" / client_name
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{label}.{source_path.name}"
    if source_path.exists():
        shutil.copyfile(source_path, backup_path)
    else:
        backup_path.write_text("", encoding="utf-8")
    return backup_path


def _latest_backup(config: BrokerConfig, client: ClientRenderConfig) -> Path:
    backup_dir = config.runtime.root / "backups" / client.name
    backups = sorted(backup_dir.glob(f"*.{client.config_path.name}"))
    if not backups:
        raise ValueError(f"no backups found for client: {client.name}")
    return backups[-1]


def _quote_toml(value: str) -> str:
    return f'"{_escape_toml_string(value)}"'


def _escape_toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _json_line(value: object) -> str:
    def default(obj: object) -> str:
        if is_dataclass(obj) and not isinstance(obj, type):
            return asdict(obj)
        if isinstance(obj, Path):
            return str(obj)
        raise TypeError(f"cannot encode {type(obj).__name__}")

    return json.dumps(value, default=default, sort_keys=True) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
