"""Local governance bundle publishing manifests."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Mapping

from mcp_broker.bundle_loader import BundleValidationError, validate_bundle_file

PUBLISH_SCHEMA_VERSION = 1
PUBLISH_MANIFEST_SUFFIX = ".publish.json"
PROMOTION_CANDIDATE = "candidate"
SUPPORTED_PROMOTION_STATES = frozenset(
    ("candidate", "canary", "staged", "stable", "deprecated")
)
REQUIRED_PROVENANCE_FIELDS = ("repository", "commit", "builder")
SAFE_MANIFEST_PART_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class GovernancePublishError(ValueError):
    """Raised when a governance bundle cannot be published."""


def publish_bundle(
    *,
    bundle_path: Path,
    output_dir: Path,
    signature_ref: str,
    provenance: Mapping[str, str],
    promotion_state: str = PROMOTION_CANDIDATE,
    revoked: bool = False,
    revocation_reason: str = "",
) -> Path:
    if not signature_ref.strip():
        raise GovernancePublishError("signature_ref is required")
    _validate_promotion_state(promotion_state)
    _validate_provenance(provenance)
    if revoked:
        raise GovernancePublishError("revoked publish candidates cannot be promoted")

    try:
        validation = validate_bundle_file(bundle_path)
    except BundleValidationError as exc:
        raise GovernancePublishError(str(exc)) from exc

    bundle = _load_bundle(bundle_path)
    manifest = _publish_manifest(
        bundle=bundle,
        signature_ref=signature_ref,
        provenance=provenance,
        promotion_state=promotion_state,
        revoked=revoked,
        revocation_reason=revocation_reason,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / _manifest_name(validation)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


def _load_bundle(bundle_path: Path) -> dict[str, Any]:
    with bundle_path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise GovernancePublishError("bundle file must contain a JSON object")
    return loaded


def _publish_manifest(
    *,
    bundle: Mapping[str, Any],
    signature_ref: str,
    provenance: Mapping[str, str],
    promotion_state: str,
    revoked: bool,
    revocation_reason: str,
) -> dict[str, Any]:
    checksum = bundle["checksum"]
    compatibility = bundle["compatibility"]
    return {
        "schema_version": PUBLISH_SCHEMA_VERSION,
        "bundle": {
            "bundle_id": bundle["bundle_id"],
            "version": bundle["version"],
            "channel": bundle["channel"],
            "digest": {
                "algorithm": checksum["algorithm"],
                "value": checksum["value"],
            },
            "compatibility": {
                "min_config_schema_version": compatibility["min_config_schema_version"],
                "max_config_schema_version": compatibility["max_config_schema_version"],
                "required_features": compatibility.get("required_features", []),
            },
        },
        "signature": {
            "required": True,
            "signature_ref": signature_ref,
        },
        "promotion": {
            "state": promotion_state,
            "channel": bundle["channel"],
        },
        "revocation": {
            "revoked": revoked,
            "reason": revocation_reason,
        },
        "provenance": dict(provenance),
        "changed_runtime_state": False,
    }


def _manifest_name(validation: Mapping[str, object]) -> str:
    bundle_id = _safe_manifest_part("bundle_id", validation["bundle_id"])
    version = _safe_manifest_part("version", validation["version"])
    checksum_algorithm = _safe_manifest_part(
        "checksum_algorithm", validation["checksum_algorithm"]
    )
    return (
        f"{bundle_id}-"
        f"{version}-"
        f"{checksum_algorithm}"
        f"{PUBLISH_MANIFEST_SUFFIX}"
    )


def _safe_manifest_part(field_name: str, value: object) -> str:
    candidate = str(value)
    if not SAFE_MANIFEST_PART_PATTERN.fullmatch(candidate):
        raise GovernancePublishError(f"unsafe publish manifest field: {field_name}")
    return candidate


def _validate_promotion_state(promotion_state: str) -> None:
    if promotion_state not in SUPPORTED_PROMOTION_STATES:
        raise GovernancePublishError(f"unsupported promotion state: {promotion_state}")


def _validate_provenance(provenance: Mapping[str, str]) -> None:
    for field_name in REQUIRED_PROVENANCE_FIELDS:
        if not str(provenance.get(field_name, "")).strip():
            raise GovernancePublishError(f"missing publish provenance field: {field_name}")
