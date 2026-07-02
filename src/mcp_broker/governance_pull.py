"""Local governance bundle pull, apply, and rollback protocol."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Mapping, Sequence
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from mcp_broker.bundle_loader import BundleValidationError, validate_bundle_file
from mcp_broker.deployments import DeploymentError, DeploymentStore


PULL_SCHEMA_VERSION = 1
SAFE_CACHE_PART_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
LOCALHOST_NAMES = frozenset(("localhost", "127.0.0.1", "::1"))


class GovernancePullError(ValueError):
    """Raised when governance pull/apply cannot proceed."""


def pull_assigned_bundle(
    *,
    source_url: str,
    assignment_decision: Mapping[str, Any],
    state_dir: Path,
    auth_ref: str,
    auth_present: bool,
) -> dict[str, object]:
    _require_auth(auth_ref=auth_ref, auth_present=auth_present)
    target = _target_from_assignment(assignment_decision)
    fetched_path = _fetch_source_to_temp(source_url=source_url, state_dir=state_dir)
    try:
        validation = validate_bundle_file(fetched_path)
    except BundleValidationError as exc:
        _unlink_if_temp(fetched_path, state_dir)
        raise GovernancePullError(str(exc)) from exc

    _validate_target_matches_bundle(target=target, validation=validation)
    digest = target["digest"]["value"]
    cache_dir = (
        state_dir.expanduser()
        / "governance-pull"
        / "cache"
        / _safe_cache_part(str(target["bundle_id"]))
        / _safe_cache_part(str(target["version"]))
        / _safe_cache_part(str(digest))
    )
    cached_bundle_path = cache_dir / "bundle.json"
    cache_record_path = cache_dir / "pull-record.json"
    cache_dir.mkdir(parents=True, exist_ok=True)
    _copy_or_replace(fetched_path, cached_bundle_path)
    _unlink_if_temp(fetched_path, state_dir)

    record = {
        "schema_version": PULL_SCHEMA_VERSION,
        "assignment_id": str(assignment_decision["assignment_id"]),
        "source": {
            "scheme": _source_scheme(source_url),
            "localhost_only": _is_localhost_source(source_url),
        },
        "target": target,
        "cached_bundle_path": str(cached_bundle_path),
        "auth": {
            "required": True,
            "auth_ref": auth_ref,
            "secret_stored": False,
        },
        "changed_runtime_state": False,
    }
    _write_json_atomic(cache_record_path, record)
    return {
        "schema_version": PULL_SCHEMA_VERSION,
        "action": "pull",
        "assignment_id": str(assignment_decision["assignment_id"]),
        "target": target,
        "cached_bundle_path": str(cached_bundle_path),
        "cache_record_path": str(cache_record_path),
        "auth": record["auth"],
        "changed_runtime_state": False,
    }


def apply_cached_bundle(
    *,
    pull_record_path: Path,
    state_dir: Path,
    approval_record: Mapping[str, Any],
) -> dict[str, object]:
    pull_record = _load_json_mapping(pull_record_path)
    _validate_approval(pull_record=pull_record, approval_record=approval_record)
    cached_bundle_path = Path(str(pull_record["cached_bundle_path"]))
    if not cached_bundle_path.is_file():
        raise GovernancePullError(f"cached bundle not found: {cached_bundle_path}")

    try:
        deployment = DeploymentStore(state_dir).record_deployment(cached_bundle_path)
    except (BundleValidationError, DeploymentError, OSError, json.JSONDecodeError) as exc:
        raise GovernancePullError(str(exc)) from exc

    return {
        "schema_version": PULL_SCHEMA_VERSION,
        "action": "apply",
        "deployment_id": deployment["deployment_id"],
        "bundle_id": deployment["bundle_id"],
        "bundle_version": deployment["bundle_version"],
        "changed_runtime_state": True,
    }


def rollback_governance_bundle(state_dir: Path) -> dict[str, object]:
    try:
        rollback = DeploymentStore(state_dir).rollback()
    except (DeploymentError, OSError, json.JSONDecodeError) as exc:
        raise GovernancePullError(str(exc)) from exc
    return {
        "schema_version": PULL_SCHEMA_VERSION,
        "action": "rollback",
        "active_deployment_id": rollback["active_deployment_id"],
        "previous_deployment_id": rollback["previous_deployment_id"],
        "changed_runtime_state": True,
    }


def _require_auth(*, auth_ref: str, auth_present: bool) -> None:
    if not auth_ref.strip() or not auth_present:
        raise GovernancePullError("governance fetch auth is required")
    if not (auth_ref.startswith("env:") or auth_ref.startswith("keychain:")):
        raise GovernancePullError("governance fetch auth_ref must use env: or keychain:")


def _target_from_assignment(assignment_decision: Mapping[str, Any]) -> dict[str, Any]:
    if assignment_decision.get("schema_version") != PULL_SCHEMA_VERSION:
        raise GovernancePullError("unsupported assignment decision schema_version")
    if not str(assignment_decision.get("assignment_id", "")).strip():
        raise GovernancePullError("assignment_id is required")
    target = assignment_decision.get("target")
    if not isinstance(target, Mapping):
        raise GovernancePullError("assignment target is required")
    digest = target.get("digest")
    if not isinstance(digest, Mapping):
        raise GovernancePullError("assignment target digest is required")
    return {
        "bundle_id": str(target["bundle_id"]),
        "version": str(target["version"]),
        "channel": str(target["channel"]),
        "digest": {
            "algorithm": str(digest["algorithm"]),
            "value": str(digest["value"]).lower(),
        },
    }


def _fetch_source_to_temp(*, source_url: str, state_dir: Path) -> Path:
    parsed = urlparse(source_url)
    if parsed.scheme == "file":
        source_path = Path(unquote(parsed.path))
        if not source_path.is_file():
            raise GovernancePullError(f"governance bundle source not found: {source_path}")
        return source_path
    if parsed.scheme in ("http", "https"):
        if parsed.hostname not in LOCALHOST_NAMES:
            raise GovernancePullError("governance fetch supports only file:// or localhost URLs")
        return _fetch_localhost_url(source_url=source_url, state_dir=state_dir)
    raise GovernancePullError("governance fetch supports only file:// or localhost URLs")


def _fetch_localhost_url(*, source_url: str, state_dir: Path) -> Path:
    temp_dir = state_dir.expanduser() / "governance-pull" / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_path = temp_dir / "fetched-bundle.json.tmp"
    request = Request(source_url, headers={"X-MCP-Broker-Governance-Fetch": "present"})
    try:
        with urlopen(request, timeout=10) as response:
            temp_path.write_bytes(response.read())
    except OSError as exc:
        raise GovernancePullError(f"governance fetch failed: {exc}") from exc
    return temp_path


def _validate_target_matches_bundle(
    *,
    target: Mapping[str, Any],
    validation: Mapping[str, object],
) -> None:
    if target["bundle_id"] != validation["bundle_id"]:
        raise GovernancePullError("assigned bundle target mismatch")
    if target["version"] != validation["version"]:
        raise GovernancePullError("assigned bundle target mismatch")
    if target["digest"]["algorithm"] != validation["checksum_algorithm"]:
        raise GovernancePullError("assigned bundle digest mismatch")
    bundle = _load_json_mapping(Path(str(validation["bundle_path"])))
    actual_digest = str(bundle["checksum"]["value"]).lower()
    if target["digest"]["value"] != actual_digest:
        raise GovernancePullError("assigned bundle digest mismatch")


def _validate_approval(
    *,
    pull_record: Mapping[str, Any],
    approval_record: Mapping[str, Any],
) -> None:
    if approval_record.get("schema_version") != PULL_SCHEMA_VERSION:
        raise GovernancePullError("unsupported approval schema_version")
    if approval_record.get("approved") is not True:
        raise GovernancePullError("local approval is required")
    for field_name in ("approved_by", "reason", "assignment_id", "target"):
        if not approval_record.get(field_name):
            raise GovernancePullError(f"approval field is required: {field_name}")
    if approval_record["assignment_id"] != pull_record["assignment_id"]:
        raise GovernancePullError("approval assignment does not match pull record")
    if approval_record["target"] != pull_record["target"]:
        raise GovernancePullError("approval target does not match pull record")


def _safe_cache_part(value: str) -> str:
    if not SAFE_CACHE_PART_PATTERN.fullmatch(value):
        raise GovernancePullError("unsafe governance cache field")
    return value


def _source_scheme(source_url: str) -> str:
    return urlparse(source_url).scheme


def _is_localhost_source(source_url: str) -> bool:
    parsed = urlparse(source_url)
    return parsed.scheme == "file" or parsed.hostname in LOCALHOST_NAMES


def _copy_or_replace(source_path: Path, destination_path: Path) -> None:
    tmp_path = destination_path.with_name(f"{destination_path.name}.tmp")
    shutil.copyfile(source_path, tmp_path)
    os.replace(tmp_path, destination_path)


def _unlink_if_temp(path: Path, state_dir: Path) -> None:
    try:
        path.relative_to(state_dir.expanduser() / "governance-pull" / "tmp")
    except ValueError:
        return
    path.unlink(missing_ok=True)


def _load_json_mapping(path: Path) -> dict[str, Any]:
    with path.expanduser().open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise GovernancePullError(f"expected JSON object: {path}")
    return loaded


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp_path, path)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.governance_command == "pull":
            return _pull(args)
        if args.governance_command == "apply":
            return _apply(args)
        if args.governance_command == "rollback":
            return _rollback(args)
    except (GovernancePullError, OSError, json.JSONDecodeError) as exc:
        sys.stdout.write(f"{exc}\n")
        return 1
    raise GovernancePullError(f"unknown governance command: {args.governance_command}")


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull, apply, and roll back governance bundles")
    subparsers = parser.add_subparsers(dest="governance_command", required=True)
    pull = subparsers.add_parser("pull", help="Fetch an assigned governance bundle into cache")
    pull.add_argument("--source", required=True)
    pull.add_argument("--assignment-decision", required=True, type=Path)
    pull.add_argument("--state-dir", required=True, type=Path)
    pull.add_argument("--auth-ref", required=True)
    pull.add_argument("--auth-present", action="store_true")
    apply = subparsers.add_parser("apply", help="Apply a cached governance bundle after approval")
    apply.add_argument("--pull-record", required=True, type=Path)
    apply.add_argument("--state-dir", required=True, type=Path)
    apply.add_argument("--approval", required=True, type=Path)
    rollback = subparsers.add_parser("rollback", help="Roll back the active governance deployment")
    rollback.add_argument("--state-dir", required=True, type=Path)
    return parser.parse_args(argv)


def _pull(args: argparse.Namespace) -> int:
    report = pull_assigned_bundle(
        source_url=args.source,
        assignment_decision=_load_json_mapping(args.assignment_decision),
        state_dir=args.state_dir,
        auth_ref=args.auth_ref,
        auth_present=args.auth_present,
    )
    sys.stdout.write(
        "governance bundle pulled: "
        f"{report['target']['bundle_id']} {report['target']['version']} "
        f"record={report['cache_record_path']}\n"
    )
    return 0


def _apply(args: argparse.Namespace) -> int:
    report = apply_cached_bundle(
        pull_record_path=args.pull_record,
        state_dir=args.state_dir,
        approval_record=_load_json_mapping(args.approval),
    )
    sys.stdout.write(
        "governance bundle applied: "
        f"{report['deployment_id']}\n"
    )
    return 0


def _rollback(args: argparse.Namespace) -> int:
    report = rollback_governance_bundle(args.state_dir)
    sys.stdout.write(
        "governance bundle rolled back: "
        f"{report['active_deployment_id']} previous={report['previous_deployment_id']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
