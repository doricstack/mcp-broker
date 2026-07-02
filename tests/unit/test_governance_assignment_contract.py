import json
from pathlib import Path
from typing import Any

import pytest

from tests.support.bundles import minimal_bundle, write_signed_bundle


pytestmark = pytest.mark.unit


PUBLISH_PROVENANCE = {
    "repository": "mcp-broker",
    "commit": "abc1234",
    "builder": "local-publisher",
}
SIGNATURE_REF = "sigstore:governance-bundle.sig"


def _published_manifest(
    tmp_path: Path,
    *,
    bundle_id: str = "personal-local",
    version: str = "2026.07.01",
    channel: str = "stable",
) -> dict[str, Any]:
    from mcp_broker.governance_publish import publish_bundle

    bundle = minimal_bundle()
    bundle["bundle_id"] = bundle_id
    bundle["version"] = version
    bundle["channel"] = channel
    bundle_path = write_signed_bundle(
        tmp_path / f"{bundle_id}-{version}-{channel}.json",
        bundle,
    )
    manifest_path = publish_bundle(
        bundle_path=bundle_path,
        output_dir=tmp_path / "published",
        signature_ref=SIGNATURE_REF,
        provenance=PUBLISH_PROVENANCE,
        promotion_state="candidate",
    )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def test_assignment_contract_matches_broker_user_team_channel_and_ring(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_assignment import evaluate_assignment

    published = _published_manifest(tmp_path)
    assignment = {
        "schema_version": 1,
        "assignments": [
            {
                "assignment_id": "team-stable-ring",
                "priority": 100,
                "match": {
                    "broker_ids": ["broker-west-1"],
                    "users": ["engineer-1"],
                    "teams": ["platform"],
                    "channels": ["stable"],
                    "rings": ["canary"],
                },
                "target": {
                    "bundle_id": "personal-local",
                    "version": "2026.07.01",
                    "channel": "stable",
                },
            }
        ],
    }
    context = {
        "broker_id": "broker-west-1",
        "user": "engineer-1",
        "teams": ["platform"],
        "channel": "stable",
        "ring": "canary",
    }

    decision = evaluate_assignment(
        assignment_source=assignment,
        published_manifests=[published],
        broker_context=context,
    )

    assert decision == {
        "schema_version": 1,
        "assignment_id": "team-stable-ring",
        "matched_by": {
            "broker_id": "broker-west-1",
            "user": "engineer-1",
            "teams": ["platform"],
            "channel": "stable",
            "ring": "canary",
        },
        "target": {
            "bundle_id": "personal-local",
            "version": "2026.07.01",
            "channel": "stable",
            "digest": published["bundle"]["digest"],
        },
        "changed_runtime_state": False,
    }


def test_assignment_contract_rejects_unpublished_bundle_reference(tmp_path: Path) -> None:
    from mcp_broker.governance_assignment import (
        GovernanceAssignmentError,
        evaluate_assignment,
    )

    published = _published_manifest(tmp_path, version="2026.07.01")
    assignment = {
        "schema_version": 1,
        "assignments": [
            {
                "assignment_id": "unknown-version",
                "priority": 10,
                "match": {"teams": ["platform"]},
                "target": {
                    "bundle_id": "personal-local",
                    "version": "2026.07.02",
                    "channel": "stable",
                },
            }
        ],
    }

    with pytest.raises(GovernanceAssignmentError, match="unpublished bundle target"):
        evaluate_assignment(
            assignment_source=assignment,
            published_manifests=[published],
            broker_context={"teams": ["platform"], "channel": "stable"},
        )


def test_assignment_contract_rejects_ambiguous_same_priority_matches(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_assignment import (
        GovernanceAssignmentError,
        evaluate_assignment,
    )

    stable = _published_manifest(tmp_path, version="2026.07.01", channel="stable")
    canary = _published_manifest(tmp_path, version="2026.07.02", channel="canary")
    assignment = {
        "schema_version": 1,
        "assignments": [
            {
                "assignment_id": "stable-platform",
                "priority": 50,
                "match": {"teams": ["platform"]},
                "target": {
                    "bundle_id": "personal-local",
                    "version": "2026.07.01",
                    "channel": "stable",
                },
            },
            {
                "assignment_id": "canary-platform",
                "priority": 50,
                "match": {"teams": ["platform"]},
                "target": {
                    "bundle_id": "personal-local",
                    "version": "2026.07.02",
                    "channel": "canary",
                },
            },
        ],
    }

    with pytest.raises(GovernanceAssignmentError, match="ambiguous assignment matches"):
        evaluate_assignment(
            assignment_source=assignment,
            published_manifests=[stable, canary],
            broker_context={"teams": ["platform"], "channel": "stable"},
        )


def test_assignment_contract_rejects_scalar_match_fields(tmp_path: Path) -> None:
    from mcp_broker.governance_assignment import (
        GovernanceAssignmentError,
        evaluate_assignment,
    )

    published = _published_manifest(tmp_path)
    assignment = {
        "schema_version": 1,
        "assignments": [
            {
                "assignment_id": "invalid-team-match",
                "priority": 10,
                "match": {"teams": "platform"},
                "target": {
                    "bundle_id": "personal-local",
                    "version": "2026.07.01",
                    "channel": "stable",
                },
            }
        ],
    }

    with pytest.raises(GovernanceAssignmentError, match="assignment match field must be a list"):
        evaluate_assignment(
            assignment_source=assignment,
            published_manifests=[published],
            broker_context={"teams": ["platform"], "channel": "stable"},
        )


@pytest.mark.parametrize(
    "assignment_source, expected_error",
    [
        (
            {
                "schema_version": 1,
                "assignments": [],
                "metadata": {"local_path": "/var/tmp/private.yaml"},
            },
            "local paths are not allowed",
        ),
        (
            {
                "schema_version": 1,
                "assignments": [],
                "metadata": {"owner": "person@example.com"},
            },
            "account names are not allowed",
        ),
        (
            {
                "schema_version": 1,
                "assignments": [],
                "metadata": {"api_token": "example-token-value"},
            },
            "secret values are not allowed",
        ),
    ],
)
def test_assignment_contract_rejects_private_or_secret_assignment_source_values(
    tmp_path: Path,
    assignment_source: dict[str, Any],
    expected_error: str,
) -> None:
    from mcp_broker.governance_assignment import (
        GovernanceAssignmentError,
        evaluate_assignment,
    )

    published = _published_manifest(tmp_path)

    with pytest.raises(GovernanceAssignmentError, match=expected_error):
        evaluate_assignment(
            assignment_source=assignment_source,
            published_manifests=[published],
            broker_context={"broker_id": "broker-west-1"},
        )
