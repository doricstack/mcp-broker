"""Config-backed policy for hiding duplicate Codex app connectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from glob import glob
import json
from pathlib import Path
import shutil
from typing import Any


@dataclass(frozen=True)
class ConnectorSelector:
    id: str | None = None
    name: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class CodexAppConnectorPolicy:
    enabled: bool = False
    app_directory_globs: tuple[str, ...] = ()
    tools_cache_globs: tuple[str, ...] = ()
    disable_connectors: tuple[ConnectorSelector, ...] = ()


@dataclass(frozen=True)
class CodexAppPolicyResult:
    matched_app_directory_files: tuple[Path, ...] = ()
    matched_tools_cache_files: tuple[Path, ...] = ()
    changed_files: tuple[Path, ...] = ()
    disabled_connectors: int = 0
    removed_tools: int = 0
    backups: tuple[Path, ...] = ()
    dry_run: bool = True
    warnings: tuple[str, ...] = ()


def apply_codex_app_policy(
    policy: CodexAppConnectorPolicy | None,
    *,
    backup_dir: Path,
    backup_label: str,
    dry_run: bool,
) -> CodexAppPolicyResult:
    if policy is None or not policy.enabled:
        return CodexAppPolicyResult(dry_run=dry_run)

    app_directory_files = _match_paths(policy.app_directory_globs)
    tools_cache_files = _match_paths(policy.tools_cache_globs)
    warnings = _missing_glob_warnings("app_directory_globs", policy.app_directory_globs)
    warnings += _missing_glob_warnings("tools_cache_globs", policy.tools_cache_globs)
    result = _apply_policy_to_files(
        policy=policy,
        app_directory_files=app_directory_files,
        tools_cache_files=tools_cache_files,
        backup_dir=backup_dir,
        backup_label=backup_label,
        dry_run=dry_run,
    )
    return CodexAppPolicyResult(
        matched_app_directory_files=app_directory_files,
        matched_tools_cache_files=tools_cache_files,
        warnings=tuple(warnings),
        **result,
    )


def _apply_policy_to_files(
    *,
    policy: CodexAppConnectorPolicy,
    app_directory_files: tuple[Path, ...],
    tools_cache_files: tuple[Path, ...],
    backup_dir: Path,
    backup_label: str,
    dry_run: bool,
) -> dict[str, object]:

    changed_files: list[Path] = []
    backups: list[Path] = []
    disabled_connectors = 0
    removed_tools = 0

    for path in app_directory_files:
        payload = _read_json_mapping(path)
        changed, disabled = _disable_connectors(payload, policy.disable_connectors)
        disabled_connectors += disabled
        if changed:
            changed_files.append(path)
            if not dry_run:
                backups.append(_backup(path, backup_dir=backup_dir, backup_label=backup_label))
                _write_json(path, payload)

    for path in tools_cache_files:
        payload = _read_json_mapping(path)
        changed, removed = _remove_connector_tools(payload, policy.disable_connectors)
        removed_tools += removed
        if changed:
            changed_files.append(path)
            if not dry_run:
                backups.append(_backup(path, backup_dir=backup_dir, backup_label=backup_label))
                _write_json(path, payload)

    return {
        "changed_files": tuple(changed_files),
        "disabled_connectors": disabled_connectors,
        "removed_tools": removed_tools,
        "backups": tuple(backups),
        "dry_run": dry_run,
    }


def _match_paths(patterns: tuple[str, ...]) -> tuple[Path, ...]:
    matched: list[Path] = []
    for pattern in patterns:
        matched.extend(Path(path) for path in glob(pattern))
    return tuple(sorted(set(matched)))


def _missing_glob_warnings(label: str, patterns: tuple[str, ...]) -> tuple[str, ...]:
    warnings: list[str] = []
    for pattern in patterns:
        if not glob(pattern):
            warnings.append(f"{label} matched no files: {pattern}")
    return tuple(warnings)


def _read_json_mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_bytes())
    if not isinstance(payload, dict):
        raise ValueError(f"Codex app cache must be a JSON object: {path}")
    return payload


def _disable_connectors(
    payload: dict[str, Any],
    selectors: tuple[ConnectorSelector, ...],
) -> tuple[bool, int]:
    connectors = payload.get("connectors")
    if not isinstance(connectors, list):
        raise ValueError("Codex app directory cache must contain a connectors list")
    changed = False
    disabled = 0
    for connector in connectors:
        if not isinstance(connector, dict):
            raise ValueError("Codex app directory connectors must be objects")
        if _matches_connector(connector, selectors) and connector.get("isEnabled") is not False:
            connector["isEnabled"] = False
            changed = True
            disabled += 1
    return changed, disabled


def _remove_connector_tools(
    payload: dict[str, Any],
    selectors: tuple[ConnectorSelector, ...],
) -> tuple[bool, int]:
    tools = payload.get("tools")
    if not isinstance(tools, list):
        raise ValueError("Codex app tools cache must contain a tools list")
    kept: list[Any] = []
    removed = 0
    for tool in tools:
        if not isinstance(tool, dict):
            raise ValueError("Codex app tool records must be objects")
        if _matches_tool(tool, selectors):
            removed += 1
        else:
            kept.append(tool)
    if removed:
        payload["tools"] = kept
    return removed > 0, removed


def _matches_connector(connector: dict[str, Any], selectors: tuple[ConnectorSelector, ...]) -> bool:
    connector_id = _string_or_none(connector.get("id"))
    connector_name = _string_or_none(connector.get("name"))
    return _matches_values(connector_id, connector_name, selectors)


def _matches_tool(tool: dict[str, Any], selectors: tuple[ConnectorSelector, ...]) -> bool:
    tool_payload = tool.get("tool")
    meta_payload = tool_payload.get("_meta") if isinstance(tool_payload, dict) else {}
    meta = meta_payload if isinstance(meta_payload, dict) else {}
    connector_id = _string_or_none(tool.get("connector_id")) or _string_or_none(
        meta.get("connector_id")
    )
    connector_name = _string_or_none(tool.get("connector_name")) or _string_or_none(
        meta.get("connector_name")
    )
    return _matches_values(connector_id, connector_name, selectors)


def _matches_values(
    connector_id: str | None,
    connector_name: str | None,
    selectors: tuple[ConnectorSelector, ...],
) -> bool:
    for selector in selectors:
        if selector.id and selector.id == connector_id:
            return True
        if selector.name and selector.name == connector_name:
            return True
    return False


def _string_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _backup(path: Path, *, backup_dir: Path, backup_label: str) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"{backup_label}.{path.name}"
    shutil.copyfile(path, backup_path)
    return backup_path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_bytes((json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
