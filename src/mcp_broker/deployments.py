"""Transactional deployment state for desired-state bundles."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Sequence

from mcp_broker.bundle_loader import BundleValidationError, bundle_checksum, validate_bundle_file


class DeploymentError(ValueError):
    """Raised when deployment state cannot be read or changed."""


@dataclass(frozen=True)
class DeploymentStore:
    state_dir: Path

    @property
    def deployments_dir(self) -> Path:
        return self.state_dir.expanduser() / "deployments"

    @property
    def records_dir(self) -> Path:
        return self.deployments_dir / "records"

    @property
    def active_pointer(self) -> Path:
        return self.deployments_dir / "active.json"

    @property
    def previous_pointer(self) -> Path:
        return self.deployments_dir / "previous.json"

    @property
    def journal_path(self) -> Path:
        return self.deployments_dir / "rollback-journal.jsonl"

    def record_deployment(self, bundle_path: Path) -> dict[str, object]:
        bundle = _load_bundle(bundle_path)
        validation = validate_bundle_file(bundle_path)
        checksum = bundle_checksum(bundle)
        deployment_id = _deployment_id(
            str(validation["bundle_id"]),
            str(validation["version"]),
            checksum,
        )
        self.records_dir.mkdir(parents=True, exist_ok=True)
        current_active = _read_pointer(self.active_pointer)
        record_path = self.records_dir / f"{deployment_id}.json"
        record = {
            "deployment_id": deployment_id,
            "bundle_id": validation["bundle_id"],
            "bundle_version": validation["version"],
            "bundle_path": str(bundle_path.expanduser()),
            "schema_version": validation["schema_version"],
            "checksum": {
                "algorithm": validation["checksum_algorithm"],
                "value": checksum,
            },
            "status": "active",
            "created_at": _utc_now(),
        }

        _write_json_atomic(record_path, record)
        _write_json_atomic(self.active_pointer, _pointer(deployment_id, record_path))
        if current_active is not None:
            _write_json_atomic(self.previous_pointer, current_active)
        self._append_journal(
            {
                "action": "activate",
                "deployment_id": deployment_id,
                "previous_deployment_id": (
                    current_active["deployment_id"] if current_active is not None else None
                ),
            }
        )
        return {**record, "record_path": str(record_path)}

    def rollback(self) -> dict[str, object]:
        active = _require_pointer(self.active_pointer, "active deployment pointer is missing")
        previous = _require_pointer(self.previous_pointer, "previous deployment pointer is missing")
        _require_record(previous)
        _write_json_atomic(self.active_pointer, previous)
        _write_json_atomic(self.previous_pointer, active)
        self._append_journal(
            {
                "action": "rollback",
                "active_deployment_id": previous["deployment_id"],
                "previous_deployment_id": active["deployment_id"],
            }
        )
        return {
            "active_deployment_id": previous["deployment_id"],
            "previous_deployment_id": active["deployment_id"],
        }

    def recover(self) -> dict[str, object]:
        removed = self._remove_partial_files()
        active = _read_pointer(self.active_pointer)
        recovered = False
        if active is not None and not Path(str(active["record_path"])).is_file():
            replacement = self._latest_record_pointer()
            if replacement is None:
                raise DeploymentError("active deployment record is missing and no records exist")
            _write_json_atomic(self.active_pointer, replacement)
            active = replacement
            recovered = True
        if active is None:
            replacement = self._latest_record_pointer()
            if replacement is not None:
                _write_json_atomic(self.active_pointer, replacement)
                active = replacement
                recovered = True
        if recovered or removed:
            self._append_journal(
                {
                    "action": "recover",
                    "active_deployment_id": active["deployment_id"] if active else None,
                    "removed_partial_files": removed,
                }
            )
        return {
            "active_deployment_id": active["deployment_id"] if active else None,
            "recovered": recovered,
            "removed_partial_files": removed,
        }

    def dry_run_stage(self, bundle_path: Path) -> dict[str, object]:
        validation = validate_bundle_file(bundle_path)
        bundle = _load_bundle(bundle_path)
        return {
            "bundle_path": str(bundle_path.expanduser()),
            "bundle_id": validation["bundle_id"],
            "bundle_version": validation["version"],
            "deployment_id": _deployment_id(
                str(validation["bundle_id"]),
                str(validation["version"]),
                bundle_checksum(bundle),
            ),
            "would_change_runtime_state": False,
        }

    def _append_journal(self, entry: dict[str, object]) -> None:
        self.deployments_dir.mkdir(parents=True, exist_ok=True)
        payload = {**entry, "ts": _utc_now()}
        with self.journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")

    def _latest_record_pointer(self) -> dict[str, str] | None:
        if not self.records_dir.exists():
            return None
        records = sorted(self.records_dir.glob("*.json"), key=lambda path: path.stat().st_mtime)
        if not records:
            return None
        record = _read_json(records[-1])
        return _pointer(str(record["deployment_id"]), records[-1])

    def _remove_partial_files(self) -> list[str]:
        if not self.deployments_dir.exists():
            return []
        partials = sorted(self.deployments_dir.rglob("*.tmp"))
        removed: list[str] = []
        for partial in partials:
            removed.append(str(partial))
            partial.unlink()
        return removed


def _load_bundle(bundle_path: Path) -> dict[str, Any]:
    with bundle_path.expanduser().open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise DeploymentError("bundle file must contain a JSON object")
    return loaded


def _deployment_id(bundle_id: str, version: str, checksum: str) -> str:
    raw = f"{bundle_id}-{version}-{checksum[:12]}"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")


def _pointer(deployment_id: str, record_path: Path) -> dict[str, str]:
    return {"deployment_id": deployment_id, "record_path": str(record_path)}


def _read_pointer(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    data = _read_json(path)
    return {"deployment_id": str(data["deployment_id"]), "record_path": str(data["record_path"])}


def _require_pointer(path: Path, message: str) -> dict[str, str]:
    pointer = _read_pointer(path)
    if pointer is None:
        raise DeploymentError(message)
    return pointer


def _require_record(pointer: dict[str, str]) -> None:
    if not Path(pointer["record_path"]).is_file():
        raise DeploymentError(f"deployment record not found: {pointer['record_path']}")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise DeploymentError(f"expected JSON object: {path}")
    return loaded


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    store = DeploymentStore(args.state_dir)
    try:
        if args.deployment_command == "stage":
            return _stage(args, store)
        if args.deployment_command == "rollback":
            return _rollback(store)
        if args.deployment_command == "recover":
            return _recover(store)
    except (BundleValidationError, DeploymentError, OSError, json.JSONDecodeError) as exc:
        sys.stdout.write(f"{exc}\n")
        return 1
    raise DeploymentError(f"unknown deployment command: {args.deployment_command}")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manage mcp-broker deployment state")
    subparsers = parser.add_subparsers(dest="deployment_command", required=True)
    stage = subparsers.add_parser("stage", help="Validate and record a bundle deployment")
    stage.add_argument("--bundle", required=True, type=Path)
    stage.add_argument("--state-dir", required=True, type=Path)
    stage.add_argument("--dry-run", action="store_true")
    rollback = subparsers.add_parser("rollback", help="Roll back to the previous deployment")
    rollback.add_argument("--state-dir", required=True, type=Path)
    recover = subparsers.add_parser("recover", help="Recover deployment state after partial writes")
    recover.add_argument("--state-dir", required=True, type=Path)
    return parser.parse_args(argv)


def _stage(args: argparse.Namespace, store: DeploymentStore) -> int:
    if args.dry_run:
        report = store.dry_run_stage(args.bundle)
        sys.stdout.write(
            "deployment dry-run: "
            f"{report['bundle_path']} ({report['deployment_id']})\n"
        )
        return 0
    report = store.record_deployment(args.bundle)
    sys.stdout.write(
        "deployment staged: "
        f"{report['bundle_path']} ({report['deployment_id']})\n"
    )
    return 0


def _rollback(store: DeploymentStore) -> int:
    report = store.rollback()
    sys.stdout.write(
        "deployment rolled back: "
        f"{report['active_deployment_id']} previous={report['previous_deployment_id']}\n"
    )
    return 0


def _recover(store: DeploymentStore) -> int:
    report = store.recover()
    sys.stdout.write(
        "deployment recovery: "
        f"active={report['active_deployment_id']} recovered={report['recovered']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
