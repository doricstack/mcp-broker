"""Installed runtime manifest layout for plugin-managed broker runtimes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


RUNTIME_INSTALL_DIR = "runtime-install"
RUNTIME_VERSIONS_DIR = "versions"
RUNTIME_MANIFEST_NAME = "runtime-manifest.json"
ACTIVE_RUNTIME_POINTER = "active-runtime.json"
PREVIOUS_RUNTIME_POINTER = "previous-runtime.json"
_SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class RuntimeInstallError(ValueError):
    """Raised when installed runtime manifest state is invalid."""


@dataclass(frozen=True)
class RuntimeInstallStore:
    state_dir: Path

    @property
    def install_dir(self) -> Path:
        return self.state_dir.expanduser() / RUNTIME_INSTALL_DIR

    @property
    def versions_dir(self) -> Path:
        return self.install_dir / RUNTIME_VERSIONS_DIR

    @property
    def active_pointer(self) -> Path:
        return self.install_dir / ACTIVE_RUNTIME_POINTER

    @property
    def previous_pointer(self) -> Path:
        return self.install_dir / PREVIOUS_RUNTIME_POINTER

    def record_installed_runtime(
        self,
        *,
        version: str,
        runtime_path: Path,
        entrypoint: str,
        artifact_digest: str,
    ) -> dict[str, str]:
        _require_safe_version(version)
        _require_non_empty("entrypoint", entrypoint)
        _require_non_empty("artifact_digest", artifact_digest)
        runtime_id = _runtime_id(version, artifact_digest)
        manifest_path = self._manifest_path(version, runtime_id)
        manifest = {
            "artifact_digest": artifact_digest,
            "entrypoint": entrypoint,
            "runtime_id": runtime_id,
            "runtime_path": str(runtime_path.expanduser()),
            "status": "installed",
            "version": version,
        }

        current_active = _read_pointer(self.active_pointer)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _write_json_atomic(manifest_path, manifest)
            if current_active is not None:
                _write_json_atomic(self.previous_pointer, current_active)
            _write_json_atomic(self.active_pointer, _pointer(runtime_id, manifest_path))
        except OSError as exc:
            raise RuntimeInstallError(str(exc)) from exc
        return {**manifest, "manifest_path": str(manifest_path)}

    def _manifest_path(self, version: str, runtime_id: str) -> Path:
        manifest_path = self.versions_dir / version / runtime_id / RUNTIME_MANIFEST_NAME
        versions_root = self.versions_dir.resolve()
        resolved_manifest = manifest_path.resolve()
        if not resolved_manifest.is_relative_to(versions_root):
            raise RuntimeInstallError("version resolves outside runtime versions directory")
        return manifest_path


def _runtime_id(version: str, artifact_digest: str) -> str:
    raw = f"{version}-{artifact_digest[-12:]}"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")


def _require_non_empty(field: str, value: str) -> None:
    if not value.strip():
        raise RuntimeInstallError(f"{field} is required")


def _require_safe_version(version: str) -> None:
    _require_non_empty("version", version)
    if version in {".", ".."} or not _SAFE_VERSION_PATTERN.fullmatch(version):
        raise RuntimeInstallError("version must be a safe path component")


def _pointer(runtime_id: str, manifest_path: Path) -> dict[str, str]:
    return {"runtime_id": runtime_id, "manifest_path": str(manifest_path)}


def _read_pointer(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    data = _read_json(path)
    return {"runtime_id": str(data["runtime_id"]), "manifest_path": str(data["manifest_path"])}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise RuntimeInstallError(f"expected JSON object: {path}")
    return loaded


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)
