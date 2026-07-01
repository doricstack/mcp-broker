"""Local desired-state bundle validation."""

from __future__ import annotations

from dataclasses import dataclass
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from jsonschema import Draft202012Validator, ValidationError

from mcp_broker.bundle_schema import BUNDLE_SCHEMA_VERSION, load_bundle_schema
from mcp_broker.config_identity import CONFIG_SCHEMA_VERSION

ZERO_CHECKSUM = "0" * 64


class BundleValidationError(ValueError):
    """Raised when a desired-state bundle fails local validation."""


@dataclass(frozen=True)
class BundleValidationReport:
    bundle_path: Path
    bundle_id: str
    version: str
    schema_version: int
    checksum_algorithm: str
    checksum_verified: bool
    compatible: bool
    changed_runtime_state: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "bundle_path": str(self.bundle_path),
            "bundle_id": self.bundle_id,
            "version": self.version,
            "schema_version": self.schema_version,
            "checksum_algorithm": self.checksum_algorithm,
            "checksum_verified": self.checksum_verified,
            "compatible": self.compatible,
            "changed_runtime_state": self.changed_runtime_state,
        }


def validate_bundle_file(bundle_path: Path) -> dict[str, object]:
    resolved_path = bundle_path.expanduser()
    if not resolved_path.exists():
        raise BundleValidationError(f"bundle file not found: {resolved_path}")
    if not resolved_path.is_file():
        raise BundleValidationError(f"bundle path must be a file: {resolved_path}")

    bundle = _load_json_mapping(resolved_path)
    _validate_schema(bundle)
    _validate_schema_version(bundle)
    _validate_checksum(bundle)
    _validate_compatibility(bundle)

    return BundleValidationReport(
        bundle_path=resolved_path,
        bundle_id=bundle["bundle_id"],
        version=bundle["version"],
        schema_version=bundle["schema_version"],
        checksum_algorithm=bundle["checksum"]["algorithm"],
        checksum_verified=True,
        compatible=True,
    ).as_dict()


def bundle_checksum(bundle: dict[str, Any]) -> str:
    normalized = copy.deepcopy(bundle)
    normalized["checksum"]["value"] = ZERO_CHECKSUM
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_json_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        try:
            loaded = json.load(handle)
        except json.JSONDecodeError as exc:
            raise BundleValidationError(
                f"bundle file must contain valid JSON: {path}: {exc.msg}"
            ) from exc
    if not isinstance(loaded, dict):
        raise BundleValidationError(f"bundle file must contain a JSON object: {path}")
    return loaded


def _validate_schema(bundle: dict[str, Any]) -> None:
    schema = load_bundle_schema()
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(bundle), key=_error_sort_key)
    if errors:
        joined = "; ".join(_format_schema_error(error) for error in errors)
        raise BundleValidationError(f"schema validation failed: {joined}")


def _validate_schema_version(bundle: dict[str, Any]) -> None:
    if bundle["schema_version"] != BUNDLE_SCHEMA_VERSION:
        raise BundleValidationError(
            "unsupported bundle schema version: "
            f"{bundle['schema_version']} (expected {BUNDLE_SCHEMA_VERSION})"
        )


def _validate_checksum(bundle: dict[str, Any]) -> None:
    checksum = bundle["checksum"]
    expected = checksum["value"].lower()
    actual = bundle_checksum(bundle)
    if expected != actual:
        raise BundleValidationError(
            f"checksum mismatch: expected {expected}, computed {actual}"
        )


def _validate_compatibility(bundle: dict[str, Any]) -> None:
    compatibility = bundle["compatibility"]
    minimum = compatibility["min_config_schema_version"]
    maximum = compatibility["max_config_schema_version"]
    if minimum > CONFIG_SCHEMA_VERSION or maximum < CONFIG_SCHEMA_VERSION:
        raise BundleValidationError(
            "incompatible config schema version: "
            f"broker uses {CONFIG_SCHEMA_VERSION}, bundle supports {minimum}..{maximum}"
        )


def _error_sort_key(error: ValidationError) -> tuple[list[str], str]:
    return ([str(part) for part in error.absolute_path], error.message)


def _format_schema_error(error: ValidationError) -> str:
    path = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{path}: {error.message}"


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = validate_bundle_file(args.bundle)
    except BundleValidationError as exc:
        sys.stdout.write(f"{exc}\n")
        return 1
    sys.stdout.write(
        "bundle validated: "
        f"{report['bundle_path']} "
        f"({report['bundle_id']} {report['version']})\n"
    )
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an mcp-broker desired-state bundle")
    parser.add_argument("--bundle", required=True, type=Path)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
