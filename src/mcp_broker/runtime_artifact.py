"""Runtime artifact integrity and archive safety checks."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import posixpath
import tarfile
from typing import Any
import zipfile


class RuntimeArtifactError(ValueError):
    """Raised when a runtime artifact cannot be safely activated."""


@dataclass(frozen=True)
class RuntimeArtifactVerifier:
    def verify_metadata_file(self, metadata_path: Path) -> dict[str, object]:
        metadata_file = metadata_path.expanduser()
        if not metadata_file.is_file():
            raise RuntimeArtifactError(f"runtime artifact metadata not found: {metadata_file}")
        metadata = _load_metadata(metadata_file)
        artifact_path = _metadata_artifact_path(
            metadata_file.parent,
            _required_string(metadata, "artifact_path", metadata_file),
        )
        entrypoint = _required_string(metadata, "entrypoint", metadata_file)
        report = self.verify(
            artifact_path=artifact_path,
            expected_digest=_required_string(metadata, "artifact_digest", metadata_file),
            required_entrypoint=entrypoint,
        )
        return {
            **report,
            "entrypoint": entrypoint,
            "metadata_path": str(metadata_file),
            "version": _required_string(metadata, "version", metadata_file),
        }

    def verify(
        self,
        *,
        artifact_path: Path,
        expected_digest: str,
        required_entrypoint: str | None = None,
    ) -> dict[str, object]:
        artifact = artifact_path.expanduser()
        if not artifact.is_file():
            raise RuntimeArtifactError(f"runtime artifact not found: {artifact}")
        algorithm, digest = _parse_digest(expected_digest)
        if algorithm != "sha256":
            raise RuntimeArtifactError(f"unsupported runtime artifact digest: {algorithm}")
        actual_digest = _sha256(artifact)
        if actual_digest != digest:
            raise RuntimeArtifactError(
                f"digest mismatch: expected {digest}, computed {actual_digest}"
            )

        archive_format, member_count = _check_archive_members(
            artifact,
            required_entrypoint=required_entrypoint,
        )
        return {
            "artifact_path": str(artifact),
            "archive_format": archive_format,
            "digest_algorithm": algorithm,
            "digest_verified": True,
            "members_checked": member_count,
            "safe_to_activate": True,
        }


def _parse_digest(expected_digest: str) -> tuple[str, str]:
    try:
        algorithm, digest = expected_digest.split(":", 1)
    except ValueError as exc:
        raise RuntimeArtifactError("runtime artifact digest must use algorithm:value") from exc
    digest = digest.lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise RuntimeArtifactError("runtime artifact digest must be a sha256 hex value")
    return algorithm.lower(), digest


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            loaded = json.load(handle)
    except json.JSONDecodeError as exc:
        raise RuntimeArtifactError(f"invalid runtime artifact metadata: {path}") from exc
    if not isinstance(loaded, dict):
        raise RuntimeArtifactError(f"runtime artifact metadata must be an object: {path}")
    return loaded


def _required_string(data: dict[str, Any], field: str, path: Path) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeArtifactError(f"runtime artifact metadata missing {field}: {path}")
    return value


def _metadata_artifact_path(metadata_dir: Path, artifact_path: str) -> Path:
    candidate = Path(artifact_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeArtifactError("runtime artifact path must stay inside metadata directory")
    resolved = (metadata_dir / candidate).resolve(strict=False)
    if not _is_relative_to(resolved, metadata_dir.resolve(strict=False)):
        raise RuntimeArtifactError("runtime artifact path must stay inside metadata directory")
    return resolved


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _check_archive_members(
    path: Path,
    *,
    required_entrypoint: str | None = None,
) -> tuple[str, int]:
    normalized_entrypoint = (
        _require_safe_member(required_entrypoint, field_name="runtime artifact entrypoint")
        if required_entrypoint is not None
        else None
    )
    if zipfile.is_zipfile(path):
        return "zip", _check_zip_members(path, required_entrypoint=normalized_entrypoint)
    if tarfile.is_tarfile(path):
        return "tar", _check_tar_members(path, required_entrypoint=normalized_entrypoint)
    raise RuntimeArtifactError(f"unsupported runtime artifact archive: {path}")


def _check_zip_members(path: Path, *, required_entrypoint: str | None) -> int:
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not infos:
            raise RuntimeArtifactError(f"empty runtime artifact archive: {path}")
        entrypoint_found = required_entrypoint is None
        for info in infos:
            normalized = _require_safe_member(info.filename)
            if _zip_info_is_symlink(info):
                raise RuntimeArtifactError(f"unsafe archive member: {info.filename}")
            if required_entrypoint == normalized:
                if info.is_dir() or not _zip_info_is_executable(info):
                    raise RuntimeArtifactError(
                        f"runtime artifact entrypoint is not executable: {required_entrypoint}"
                    )
                entrypoint_found = True
        if not entrypoint_found:
            raise RuntimeArtifactError(
                f"runtime artifact entrypoint not found: {required_entrypoint}"
            )
        return len(infos)


def _check_tar_members(path: Path, *, required_entrypoint: str | None) -> int:
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        if not members:
            raise RuntimeArtifactError(f"empty runtime artifact archive: {path}")
        entrypoint_found = required_entrypoint is None
        for member in members:
            normalized = _require_safe_member(member.name)
            if member.issym() or member.islnk():
                raise RuntimeArtifactError(f"unsafe archive member: {member.name}")
            if not (member.isfile() or member.isdir()):
                raise RuntimeArtifactError(f"unsafe archive member: {member.name}")
            if member.linkname:
                _require_safe_member(member.linkname)
            if required_entrypoint == normalized:
                if not member.isfile() or not _tar_member_is_executable(member):
                    raise RuntimeArtifactError(
                        f"runtime artifact entrypoint is not executable: {required_entrypoint}"
                    )
                entrypoint_found = True
        if not entrypoint_found:
            raise RuntimeArtifactError(
                f"runtime artifact entrypoint not found: {required_entrypoint}"
            )
        return len(members)


def _require_safe_member(
    member_name: str,
    *,
    field_name: str = "archive member",
) -> str:
    normalized = posixpath.normpath(member_name)
    raw_parts = tuple(part for part in member_name.split("/") if part)
    parts = tuple(part for part in normalized.split("/") if part)
    if (
        not member_name.strip()
        or "\\" in member_name
        or _is_windows_drive_path(member_name)
        or _is_windows_drive_path(normalized)
        or ".." in raw_parts
        or normalized.startswith("../")
        or normalized in {"..", "."}
        or posixpath.isabs(member_name)
        or ".." in parts
    ):
        raise RuntimeArtifactError(f"unsafe {field_name}: {member_name}")
    return normalized


def _zip_info_is_symlink(info: zipfile.ZipInfo) -> bool:
    file_type = (info.external_attr >> 16) & 0o170000
    return file_type == 0o120000


def _zip_info_is_executable(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o777
    return bool(mode & 0o111)


def _tar_member_is_executable(member: tarfile.TarInfo) -> bool:
    return bool(member.mode & 0o111)


def _is_windows_drive_path(path: str) -> bool:
    first_part = path.split("/", 1)[0]
    return len(first_part) >= 2 and first_part[1] == ":" and first_part[0].isalpha()


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
    except ValueError:
        return False
    return True
