"""Audit and migrate project-local Claude MCP files."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

import yaml

from mcp_broker.config import BrokerConfig


ENV_REFERENCE_PATTERN = re.compile(
    r"^(?:[A-Za-z0-9_ -]+)?\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?$"
)
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TEXT_ENCODING = "utf-8"


@dataclass(frozen=True)
class ProjectMcpReport:
    apply: bool
    import_missing: bool
    files_scanned: int
    covered_servers: list[str] = field(default_factory=list)
    missing_servers: list[str] = field(default_factory=list)
    imported_servers: list[str] = field(default_factory=list)
    import_errors: dict[str, str] = field(default_factory=dict)
    files_changed: list[Path] = field(default_factory=list)
    files_blocked: list[Path] = field(default_factory=list)
    backups: list[Path] = field(default_factory=list)

    def to_jsonable(self) -> dict[str, object]:
        return {
            "apply": self.apply,
            "import_missing": self.import_missing,
            "files_scanned": self.files_scanned,
            "covered_servers": self.covered_servers,
            "missing_servers": self.missing_servers,
            "imported_servers": self.imported_servers,
            "import_errors": self.import_errors,
            "files_changed": [str(path) for path in self.files_changed],
            "files_blocked": [str(path) for path in self.files_blocked],
            "backups": [str(path) for path in self.backups],
        }


@dataclass(frozen=True)
class _ProjectMcpFile:
    path: Path
    data: dict[str, Any]
    servers: dict[str, Any]
    claude_project_path: str | None = None


def audit_project_mcp_files(
    *,
    config_path: Path,
    roots: Sequence[Path],
    backup_root: Path,
    import_missing: bool,
    apply: bool,
    profiles: Sequence[str],
    claude_config_path: Path | None = None,
) -> ProjectMcpReport:
    config = BrokerConfig.from_file(config_path)
    covered_names = _covered_server_names(config)
    files = [_load_mcp_file(path) for path in _find_project_mcp_files(roots, backup_root)]
    files.extend(_load_claude_project_entries(claude_config_path, roots) if claude_config_path else [])
    missing_imports: dict[str, dict[str, Any]] = {}
    import_errors: dict[str, str] = {}
    covered_servers: set[str] = set()
    missing_servers: set[str] = set()

    for project_file in files:
        for server_name, server_config in project_file.servers.items():
            if server_name in covered_names:
                covered_servers.add(server_name)
                continue
            import_config, error = _server_to_upstream(server_name, server_config, profiles)
            if error is not None:
                missing_servers.add(server_name)
                import_errors[server_name] = error
                continue
            missing_servers.add(server_name)
            if import_missing and server_name not in missing_imports:
                missing_imports[server_name] = import_config

    imported_servers: list[str] = []
    if apply and import_missing and missing_imports:
        imported_servers = _append_missing_upstreams(config_path, missing_imports)
        covered_names.update(imported_servers)

    changed_files: list[Path] = []
    blocked_files: list[Path] = []
    backups: list[Path] = []
    backed_up_paths: set[Path] = set()
    for project_file in files:
        if not project_file.servers:
            continue
        file_missing = sorted(
            server_name
            for server_name in project_file.servers
            if server_name not in covered_names
        )
        if file_missing:
            blocked_files.append(project_file.path)
            continue
        if apply:
            if project_file.path not in backed_up_paths:
                backups.append(_backup_file(project_file.path, backup_root))
                backed_up_paths.add(project_file.path)
            _write_empty_mcp_servers(project_file)
            changed_files.append(project_file.path)

    return ProjectMcpReport(
        apply=apply,
        import_missing=import_missing,
        files_scanned=len(files),
        covered_servers=sorted(covered_servers),
        missing_servers=sorted(missing_servers),
        imported_servers=sorted(imported_servers),
        import_errors=dict(sorted(import_errors.items())),
        files_changed=sorted(changed_files),
        files_blocked=sorted(blocked_files),
        backups=sorted(backups),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = audit_project_mcp_files(
        config_path=args.config,
        roots=args.root,
        backup_root=args.backup_root,
        import_missing=args.import_missing,
        apply=args.apply,
        profiles=args.profile,
        claude_config_path=args.claude_config,
    )
    sys.stdout.write(json.dumps(report.to_jsonable(), sort_keys=True) + "\n")
    return 0 if not report.files_blocked else 2


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and migrate project-local .mcp.json files")
    parser.add_argument("--config", type=Path, required=True, help="Broker YAML config")
    parser.add_argument(
        "--root",
        type=Path,
        action="append",
        required=True,
        help="Root to scan recursively; repeat for multiple roots",
    )
    parser.add_argument("--backup-root", type=Path, required=True, help="Backup directory")
    parser.add_argument("--claude-config", type=Path, help="Claude JSON config with per-project MCP entries")
    parser.add_argument(
        "--profile",
        action="append",
        help="Broker profile for imported upstreams; repeat for multiple profiles",
    )
    parser.add_argument("--import-missing", action="store_true", help="Append missing entries to broker config")
    parser.add_argument("--apply", action="store_true", help="Write backups, imports, and empty .mcp.json files")
    parsed = parser.parse_args(argv)
    if not parsed.profile:
        parsed.profile = ["codex", "claude"]
    return parsed


def _covered_server_names(config: BrokerConfig) -> set[str]:
    names: set[str] = set()
    for upstream_name, upstream in config.upstreams.items():
        names.add(upstream_name)
        if upstream.tool_prefix:
            names.add(upstream.tool_prefix)
    return names


def _find_project_mcp_files(roots: Sequence[Path], backup_root: Path) -> list[Path]:
    discovered: set[Path] = set()
    resolved_backup = backup_root.expanduser().resolve()
    for root in roots:
        expanded_root = root.expanduser()
        if not expanded_root.exists():
            continue
        for path in sorted(expanded_root.rglob(".mcp.json")):
            resolved_path = path.resolve()
            if _is_under(resolved_path, resolved_backup):
                continue
            if any(part in {".git", "node_modules", "venv-mcp-broker"} for part in path.parts):
                continue
            discovered.add(path)
    return sorted(discovered)


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _load_mcp_file(path: Path) -> _ProjectMcpFile:
    loaded = json.loads(path.read_text(encoding=TEXT_ENCODING))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    servers = loaded.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"{path} mcpServers must be an object")
    return _ProjectMcpFile(path=path, data=loaded, servers=servers)


def _load_claude_project_entries(
    claude_config_path: Path | None,
    roots: Sequence[Path],
) -> list[_ProjectMcpFile]:
    if claude_config_path is None:
        return []
    expanded_path = claude_config_path.expanduser()
    if not expanded_path.exists():
        return []
    loaded = json.loads(expanded_path.read_text(encoding=TEXT_ENCODING))
    if not isinstance(loaded, dict):
        raise ValueError(f"{expanded_path} must contain a JSON object")
    projects = loaded.get("projects", {})
    if not isinstance(projects, dict):
        raise ValueError(f"{expanded_path} projects must be an object")
    resolved_roots = [root.expanduser().resolve() for root in roots if root.expanduser().exists()]
    entries: list[_ProjectMcpFile] = []
    for project_path, project_config in projects.items():
        if not _path_matches_roots(Path(project_path).expanduser(), resolved_roots):
            continue
        if not isinstance(project_config, dict):
            raise ValueError(f"{expanded_path} projects.{project_path} must be an object")
        servers = project_config.get("mcpServers", {})
        if not isinstance(servers, dict):
            raise ValueError(f"{expanded_path} projects.{project_path}.mcpServers must be an object")
        entries.append(
            _ProjectMcpFile(
                path=expanded_path,
                data=loaded,
                servers=servers,
                claude_project_path=project_path,
            )
        )
    return entries


def _path_matches_roots(path: Path, roots: Sequence[Path]) -> bool:
    if not path.exists():
        return False
    resolved_path = path.resolve()
    return any(_is_under(resolved_path, root) for root in roots)


def _server_to_upstream(
    server_name: str,
    server_config: object,
    profiles: Sequence[str],
) -> tuple[dict[str, Any], str | None]:
    if not isinstance(server_config, dict):
        return {}, "server config must be an object"
    if _is_http_server(server_config):
        return _http_server_to_upstream(server_name, server_config, profiles)
    return _stdio_server_to_upstream(server_name, server_config, profiles)


def _is_http_server(server_config: dict[str, Any]) -> bool:
    server_type_value = server_config.get("type")
    has_http_type = (
        server_type_value is not None
        and str(server_type_value).lower() in {"http", "sse"}
    )
    return has_http_type or "url" in server_config


def _stdio_server_to_upstream(
    server_name: str,
    server_config: dict[str, Any],
    profiles: Sequence[str],
) -> tuple[dict[str, Any], str | None]:
    command = server_config.get("command")
    if not isinstance(command, str) or not command:
        return {}, "stdio server requires command"
    args = server_config.get("args", [])
    if not isinstance(args, list):
        return {}, "args must be a list"
    env, error = _parse_env_mapping(server_config.get("env", {}))
    if error is not None:
        return {}, error
    upstream = _base_import(server_name, profiles)
    upstream.update(
        {
            "transport": "stdio",
            "command": command,
            "args": [str(arg) for arg in args],
        }
    )
    if env:
        upstream["env"] = env
    return upstream, None


def _http_server_to_upstream(
    server_name: str,
    server_config: dict[str, Any],
    profiles: Sequence[str],
) -> tuple[dict[str, Any], str | None]:
    url = server_config.get("url")
    if not isinstance(url, str) or not url:
        return {}, "http server requires url"
    env, error = _parse_header_mapping(server_config.get("headers", {}))
    if error is not None:
        return {}, error
    upstream = _base_import(server_name, profiles)
    upstream.update(
        {
            "transport": "http",
            "command": url,
        }
    )
    if env:
        upstream["env"] = env
    return upstream, None


def _base_import(server_name: str, profiles: Sequence[str]) -> dict[str, Any]:
    return {
        "enabled": True,
        "mode": "shared",
        "purpose": f"Imported from project-local .mcp.json entry {server_name}.",
        "tags": ["project-import"],
        "tool_prefix": server_name,
        "state_dir": f"upstreams/{server_name}",
        "profiles": list(profiles),
    }


def _parse_env_mapping(value: object) -> tuple[dict[str, str], str | None]:
    if not isinstance(value, dict):
        return {}, "env must be an object"
    parsed: dict[str, str] = {}
    for target_name, source_value in value.items():
        if not isinstance(target_name, str) or not ENV_NAME_PATTERN.match(target_name):
            return {}, "env keys must be environment variable names"
        source_name = _extract_env_source(source_value)
        if source_name is None:
            return {}, f"env.{target_name} must reference an environment variable"
        parsed[target_name] = source_name
    return parsed, None


def _parse_header_mapping(value: object) -> tuple[dict[str, str], str | None]:
    if not isinstance(value, dict):
        return {}, "headers must be an object"
    parsed: dict[str, str] = {}
    for header_name, source_value in value.items():
        if not isinstance(header_name, str):
            return {}, "header keys must be strings"
        target_name = _header_env_name(header_name)
        source_name = _extract_env_source(source_value)
        if source_name is None:
            return {}, f"headers.{header_name} must reference an environment variable"
        parsed[target_name] = source_name
    return parsed, None


def _extract_env_source(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if ENV_NAME_PATTERN.match(value):
        return value
    match = ENV_REFERENCE_PATTERN.match(value)
    if match is None:
        return None
    return match.group(1)


def _header_env_name(header_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", header_name).strip("_").upper()
    return normalized or "HEADER"


def _append_missing_upstreams(
    config_path: Path,
    missing_imports: dict[str, dict[str, Any]],
) -> list[str]:
    original = config_path.read_text(encoding=TEXT_ENCODING)
    addition = _yaml_upstream_addition(missing_imports)
    updated = _insert_under_upstreams(original, addition)
    config_path.write_text(updated, encoding=TEXT_ENCODING)
    try:
        BrokerConfig.from_file(config_path)
    except Exception:
        config_path.write_text(original, encoding=TEXT_ENCODING)
        raise
    return sorted(missing_imports)


def _yaml_upstream_addition(missing_imports: dict[str, dict[str, Any]]) -> str:
    dumped = yaml.safe_dump(
        missing_imports,
        sort_keys=False,
        default_flow_style=False,
    )
    return "".join(f"  {line}" if line.strip() else line for line in dumped.splitlines(True))


def _insert_under_upstreams(config_text: str, addition: str) -> str:
    lines = config_text.splitlines(True)
    upstream_index = next(
        (index for index, line in enumerate(lines) if line.strip() == "upstreams:"),
        None,
    )
    if upstream_index is None:
        prefix = "" if config_text.endswith("\n") else "\n"
        return f"{config_text}{prefix}upstreams:\n{addition}"
    insert_at = len(lines)
    for index in range(upstream_index + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.startswith((" ", "#")):
            insert_at = index
            break
    if not lines[insert_at - 1].endswith("\n"):
        lines[insert_at - 1] = lines[insert_at - 1] + "\n"
    lines.insert(insert_at, addition if addition.endswith("\n") else addition + "\n")
    return "".join(lines)


def _backup_file(path: Path, backup_root: Path) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "__", str(path.expanduser()))
    backup_path = backup_root / f"{timestamp}.{safe_name}"
    backup_path.write_text(path.read_text(encoding=TEXT_ENCODING), encoding=TEXT_ENCODING)
    return backup_path


def _write_empty_mcp_servers(project_file: _ProjectMcpFile) -> None:
    if project_file.claude_project_path is not None:
        _write_empty_claude_project_servers(project_file)
        return
    updated = dict(project_file.data)
    updated["mcpServers"] = {}
    project_file.path.write_text(
        json.dumps(updated, indent=2, sort_keys=True) + "\n",
        encoding=TEXT_ENCODING,
    )


def _write_empty_claude_project_servers(project_file: _ProjectMcpFile) -> None:
    loaded = json.loads(project_file.path.read_text(encoding=TEXT_ENCODING))
    if not isinstance(loaded, dict):
        raise ValueError(f"{project_file.path} must contain a JSON object")
    projects = loaded.get("projects", {})
    if not isinstance(projects, dict):
        raise ValueError(f"{project_file.path} projects must be an object")
    project_config = projects.get(project_file.claude_project_path)
    if not isinstance(project_config, dict):
        raise ValueError(
            f"{project_file.path} projects.{project_file.claude_project_path} must be an object"
        )
    updated_project = dict(project_config)
    updated_project["mcpServers"] = {}
    updated_projects = dict(projects)
    updated_projects[project_file.claude_project_path] = updated_project
    updated = dict(loaded)
    updated["projects"] = updated_projects
    project_file.path.write_text(
        json.dumps(updated, indent=2, sort_keys=True) + "\n",
        encoding=TEXT_ENCODING,
    )


if __name__ == "__main__":
    raise SystemExit(main())
