"""Active installed-runtime launcher planning."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Sequence

from mcp_broker.runtime_install import RuntimeInstallStore


class RuntimeLauncherError(ValueError):
    """Raised when active installed-runtime launch state is invalid."""


@dataclass(frozen=True)
class ActiveRuntimeLauncher:
    state_dir: Path

    def launch_plan(self, args: Sequence[str] = ()) -> dict[str, object]:
        store = RuntimeInstallStore(self.state_dir)
        pointer = _read_active_pointer(store.active_pointer)
        manifest_path = Path(pointer["manifest_path"])
        _require_manifest_path_in_versions_root(manifest_path, store.versions_dir)
        manifest = _read_manifest(manifest_path)
        runtime_id = str(manifest["runtime_id"])
        if runtime_id != pointer["runtime_id"]:
            raise RuntimeLauncherError("active runtime pointer does not match manifest")

        runtime_path = Path(str(manifest["runtime_path"])).expanduser()
        entrypoint = str(manifest["entrypoint"])
        executable = _entrypoint_path(runtime_path, entrypoint)
        return {
            "argv": [str(executable), *list(args)],
            "entrypoint": entrypoint,
            "manifest_path": str(manifest_path),
            "runtime_id": runtime_id,
            "runtime_path": str(runtime_path),
        }


def _read_active_pointer(path: Path) -> dict[str, str]:
    if not path.exists():
        raise RuntimeLauncherError("active runtime pointer is missing")
    data = _read_json(path)
    return {
        "runtime_id": _required_string(data, "runtime_id", path),
        "manifest_path": _required_string(data, "manifest_path", path),
    }


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise RuntimeLauncherError(f"active runtime manifest is missing: {path}")
    data = _read_json(path)
    for field in ("entrypoint", "runtime_id", "runtime_path"):
        _required_string(data, field, path)
    return data


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except json.JSONDecodeError as exc:
        raise RuntimeLauncherError(f"invalid runtime JSON: {path}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeLauncherError(f"expected JSON object: {path}")
    return loaded


def _required_string(data: dict[str, Any], field: str, path: Path) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeLauncherError(f"active runtime JSON missing {field}: {path}")
    return value


def _require_manifest_path_in_versions_root(path: Path, versions_root: Path) -> None:
    manifest_path = path.expanduser().resolve(strict=False)
    versions_root = versions_root.expanduser().resolve(strict=False)
    if not _is_relative_to(manifest_path, versions_root):
        raise RuntimeLauncherError("active runtime manifest path is outside runtime install root")
    if manifest_path.name != "runtime-manifest.json":
        raise RuntimeLauncherError("active runtime manifest path must end with runtime-manifest.json")


def _entrypoint_path(runtime_path: Path, entrypoint: str) -> Path:
    entrypoint_path = Path(entrypoint)
    if entrypoint_path.is_absolute() or ".." in entrypoint_path.parts:
        raise RuntimeLauncherError("entrypoint must stay inside runtime path")
    executable = runtime_path / entrypoint_path
    if not executable.exists():
        raise RuntimeLauncherError(f"active runtime entrypoint is missing: {executable}")
    if not _is_relative_to(executable.resolve(), runtime_path.resolve()):
        raise RuntimeLauncherError("entrypoint must stay inside runtime path")
    if not os.access(executable, os.X_OK):
        raise RuntimeLauncherError(f"active runtime entrypoint is not executable: {executable}")
    return executable


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True
