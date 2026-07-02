import json
from pathlib import Path
from typing import Any

import pytest

from tests.support.bundles import minimal_bundle, write_signed_bundle


pytestmark = pytest.mark.unit


AUTH_REF = "env:GOVERNANCE_FETCH_TOKEN"
PUBLISH_PROVENANCE = {
    "repository": "mcp-broker",
    "commit": "abc1234",
    "builder": "local-publisher",
}
SIGNATURE_REF = "sigstore:governance-bundle.sig"


def test_pull_fetches_assigned_file_bundle_into_cache_without_applying(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_pull import pull_assigned_bundle

    bundle_path, decision = _assigned_bundle(tmp_path)
    state_dir = tmp_path / "state"

    report = pull_assigned_bundle(
        source_url=bundle_path.as_uri(),
        assignment_decision=decision,
        state_dir=state_dir,
        auth_ref=AUTH_REF,
        auth_present=True,
    )

    cache_record_path = Path(str(report["cache_record_path"]))
    cached_bundle_path = Path(str(report["cached_bundle_path"]))
    cache_record = json.loads(cache_record_path.read_text(encoding="utf-8"))

    assert report["schema_version"] == 1
    assert report["action"] == "pull"
    assert report["assignment_id"] == decision["assignment_id"]
    assert report["target"] == decision["target"]
    assert report["auth"] == {
        "required": True,
        "auth_ref": AUTH_REF,
        "secret_stored": False,
    }
    assert report["changed_runtime_state"] is False
    assert cache_record["target"] == decision["target"]
    assert cache_record["changed_runtime_state"] is False
    assert cached_bundle_path.is_file()
    assert str(cached_bundle_path).startswith(str(state_dir / "governance-pull" / "cache"))
    assert not (state_dir / "deployments").exists()
    assert "governance-fetch-token" not in cache_record_path.read_text(encoding="utf-8").lower()


def test_pull_rejects_missing_auth_before_fetch(tmp_path: Path) -> None:
    from mcp_broker.governance_pull import GovernancePullError, pull_assigned_bundle

    bundle_path, decision = _assigned_bundle(tmp_path)

    with pytest.raises(GovernancePullError, match="governance fetch auth is required"):
        pull_assigned_bundle(
            source_url=bundle_path.as_uri(),
            assignment_decision=decision,
            state_dir=tmp_path / "state",
            auth_ref=AUTH_REF,
            auth_present=False,
        )


def test_pull_rejects_bundle_digest_mismatch(tmp_path: Path) -> None:
    from mcp_broker.governance_pull import GovernancePullError, pull_assigned_bundle

    bundle_path, decision = _assigned_bundle(tmp_path)
    decision["target"]["digest"]["value"] = "f" * 64

    with pytest.raises(GovernancePullError, match="assigned bundle digest mismatch"):
        pull_assigned_bundle(
            source_url=bundle_path.as_uri(),
            assignment_decision=decision,
            state_dir=tmp_path / "state",
            auth_ref=AUTH_REF,
            auth_present=True,
        )


def test_pull_rejects_incompatible_bundle_before_cache(tmp_path: Path) -> None:
    from mcp_broker.bundle_loader import bundle_checksum
    from mcp_broker.governance_pull import GovernancePullError, pull_assigned_bundle

    bundle = minimal_bundle()
    bundle["compatibility"]["min_config_schema_version"] = 2
    bundle["compatibility"]["max_config_schema_version"] = 2
    bundle_path = write_signed_bundle(tmp_path / "bundle.json", bundle)
    loaded = json.loads(bundle_path.read_text(encoding="utf-8"))
    decision = _assignment_decision(
        bundle_id=str(loaded["bundle_id"]),
        version=str(loaded["version"]),
        channel=str(loaded["channel"]),
        digest_value=bundle_checksum(loaded),
    )

    with pytest.raises(GovernancePullError, match="incompatible config schema version"):
        pull_assigned_bundle(
            source_url=bundle_path.as_uri(),
            assignment_decision=decision,
            state_dir=tmp_path / "state",
            auth_ref=AUTH_REF,
            auth_present=True,
        )
    assert not (tmp_path / "state" / "governance-pull").exists()


def test_apply_requires_local_approval_before_mutating_deployment_state(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_pull import (
        GovernancePullError,
        apply_cached_bundle,
        pull_assigned_bundle,
    )

    bundle_path, decision = _assigned_bundle(tmp_path)
    state_dir = tmp_path / "state"
    pull_report = pull_assigned_bundle(
        source_url=bundle_path.as_uri(),
        assignment_decision=decision,
        state_dir=state_dir,
        auth_ref=AUTH_REF,
        auth_present=True,
    )

    with pytest.raises(GovernancePullError, match="local approval is required"):
        apply_cached_bundle(
            pull_record_path=Path(str(pull_report["cache_record_path"])),
            state_dir=state_dir,
            approval_record={"schema_version": 1, "approved": False},
        )

    apply_report = apply_cached_bundle(
        pull_record_path=Path(str(pull_report["cache_record_path"])),
        state_dir=state_dir,
        approval_record=_approval(decision),
    )

    assert apply_report["schema_version"] == 1
    assert apply_report["action"] == "apply"
    assert apply_report["bundle_id"] == decision["target"]["bundle_id"]
    assert apply_report["bundle_version"] == decision["target"]["version"]
    assert apply_report["changed_runtime_state"] is True
    assert (state_dir / "deployments" / "active.json").is_file()


def test_rollback_delegates_to_transactional_deployment_state(tmp_path: Path) -> None:
    from mcp_broker.governance_pull import (
        apply_cached_bundle,
        pull_assigned_bundle,
        rollback_governance_bundle,
    )

    state_dir = tmp_path / "state"
    first_bundle, first_decision = _assigned_bundle(tmp_path / "first", version="2026.07.01")
    second_bundle, second_decision = _assigned_bundle(tmp_path / "second", version="2026.07.02")

    first_pull = pull_assigned_bundle(
        source_url=first_bundle.as_uri(),
        assignment_decision=first_decision,
        state_dir=state_dir,
        auth_ref=AUTH_REF,
        auth_present=True,
    )
    apply_cached_bundle(
        pull_record_path=Path(str(first_pull["cache_record_path"])),
        state_dir=state_dir,
        approval_record=_approval(first_decision),
    )
    second_pull = pull_assigned_bundle(
        source_url=second_bundle.as_uri(),
        assignment_decision=second_decision,
        state_dir=state_dir,
        auth_ref=AUTH_REF,
        auth_present=True,
    )
    second_apply = apply_cached_bundle(
        pull_record_path=Path(str(second_pull["cache_record_path"])),
        state_dir=state_dir,
        approval_record=_approval(second_decision),
    )

    rollback = rollback_governance_bundle(state_dir)

    assert rollback["schema_version"] == 1
    assert rollback["action"] == "rollback"
    assert rollback["previous_deployment_id"] == second_apply["deployment_id"]
    active = json.loads((state_dir / "deployments" / "active.json").read_text(encoding="utf-8"))
    assert active["deployment_id"] == rollback["active_deployment_id"]


def _assigned_bundle(
    tmp_path: Path,
    *,
    bundle_id: str = "personal-local",
    version: str = "2026.07.01",
    channel: str = "stable",
) -> tuple[Path, dict[str, Any]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bundle = minimal_bundle()
    bundle["bundle_id"] = bundle_id
    bundle["version"] = version
    bundle["channel"] = channel
    bundle_path = write_signed_bundle(tmp_path / "bundle.json", bundle)
    loaded = json.loads(bundle_path.read_text(encoding="utf-8"))
    return bundle_path, _assignment_decision(
        bundle_id=bundle_id,
        version=version,
        channel=channel,
        digest_value=str(loaded["checksum"]["value"]),
    )


def _assignment_decision(
    *,
    bundle_id: str,
    version: str,
    channel: str,
    digest_value: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "assignment_id": "team-stable-ring",
        "target": {
            "bundle_id": bundle_id,
            "version": version,
            "channel": channel,
            "digest": {
                "algorithm": "sha256",
                "value": digest_value,
            },
        },
        "changed_runtime_state": False,
    }


def _approval(decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "approved": True,
        "approved_by": "release-manager",
        "reason": "approved governance bundle rollout",
        "assignment_id": decision["assignment_id"],
        "target": decision["target"],
    }
