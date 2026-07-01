import json
from pathlib import Path

import pytest

from tests.support.bundles import minimal_bundle, signed_bundle, write_signed_bundle


pytestmark = pytest.mark.unit


def test_validate_bundle_file_accepts_schema_checksum_and_compatibility(tmp_path: Path) -> None:
    from mcp_broker.bundle_loader import validate_bundle_file

    bundle_path = write_signed_bundle(tmp_path / "bundle.json")

    report = validate_bundle_file(bundle_path)

    assert report == {
        "bundle_path": str(bundle_path),
        "bundle_id": "personal-local",
        "version": "2026.07.01",
        "schema_version": 1,
        "checksum_algorithm": "sha256",
        "checksum_verified": True,
        "compatible": True,
        "changed_runtime_state": False,
    }
    assert sorted(path.name for path in tmp_path.iterdir()) == ["bundle.json"]


def test_validate_bundle_file_rejects_missing_file(tmp_path: Path) -> None:
    from mcp_broker.bundle_loader import BundleValidationError, validate_bundle_file

    with pytest.raises(BundleValidationError, match="bundle file not found"):
        validate_bundle_file(tmp_path / "missing.json")


def test_validate_bundle_file_rejects_checksum_mismatch(tmp_path: Path) -> None:
    from mcp_broker.bundle_loader import BundleValidationError, validate_bundle_file

    bundle = signed_bundle()
    bundle["checksum"]["value"] = "f" * 64
    bundle_path = _write_bundle(tmp_path / "bundle.json", bundle)

    with pytest.raises(BundleValidationError, match="checksum mismatch"):
        validate_bundle_file(bundle_path)


def test_validate_bundle_file_rejects_schema_errors_before_loader(tmp_path: Path) -> None:
    from mcp_broker.bundle_loader import BundleValidationError, validate_bundle_file

    bundle = signed_bundle()
    bundle["install_script"] = "./setup.sh"
    bundle_path = _write_bundle(tmp_path / "bundle.json", bundle)

    with pytest.raises(BundleValidationError, match="schema validation failed"):
        validate_bundle_file(bundle_path)


def test_validate_bundle_file_rejects_incompatible_config_schema(tmp_path: Path) -> None:
    from mcp_broker.bundle_loader import BundleValidationError, validate_bundle_file

    bundle = minimal_bundle()
    bundle["compatibility"]["min_config_schema_version"] = 2
    bundle["compatibility"]["max_config_schema_version"] = 2
    bundle_path = write_signed_bundle(tmp_path / "bundle.json", bundle)

    with pytest.raises(BundleValidationError, match="incompatible config schema version"):
        validate_bundle_file(bundle_path)


def _write_bundle(path: Path, bundle: dict[str, object]) -> Path:
    path.write_text(json.dumps(bundle, indent=2, sort_keys=True), encoding="utf-8")
    return path
