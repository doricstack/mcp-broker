from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_broker.cli import main as cli_main
from tests.support.bundles import signed_bundle


pytestmark = [pytest.mark.unit]


def _bundle() -> dict[str, object]:
    bundle = signed_bundle()
    bundle["applies_to"] = {
        "broker_ids": ["broker-a", "broker-b", "broker-c"],
        "environments": ["local"],
    }
    bundle["policy"]["approval_required"] = True
    bundle["rollout"] = {
        "rollback_on_statuses": ["degraded", "failed"],
        "stages": [
            {"name": "canary", "broker_ids": ["broker-a"]},
            {"name": "staged", "broker_ids": ["broker-b"]},
            {"name": "broad", "broker_ids": ["broker-c"]},
        ],
    }
    return bundle


def _fleet_status(
    broker_id: str,
    *,
    status: str = "running",
    schema_version: int = 1,
) -> dict[str, object]:
    return {
        "identity": {
            "active_profiles": ["codex"],
            "broker_id": broker_id,
            "bundle_version": "unbundled",
            "environment": "local",
            "schema_version": schema_version,
        },
        "health": {
            "last_request_status": "ok",
            "started_at": "2026-07-01T12:00:00+00:00",
            "status": status,
            "updated_at": "2026-07-01T12:03:00+00:00",
        },
        "request_counters": {
            "request_errors_total": 0,
            "requests_total": 10,
        },
        "upstreams": {},
    }


def test_rollout_simulator_requires_approval_before_staging() -> None:
    from mcp_broker.rollout_simulator import simulate_rollout

    result = simulate_rollout(
        bundle=_bundle(),
        fleet_statuses=[
            _fleet_status("broker-a"),
            _fleet_status("broker-b"),
            _fleet_status("broker-c"),
        ],
        approval_granted=False,
    )

    assert result == {
        "mode": "local_simulation_only",
        "state": "approval_required",
        "decisions": [],
        "reasons": ["policy approval_required is true and approval was not granted"],
    }


def test_rollout_simulator_plans_canary_staged_and_broad_rollout() -> None:
    from mcp_broker.rollout_simulator import simulate_rollout

    result = simulate_rollout(
        bundle=_bundle(),
        fleet_statuses=[
            _fleet_status("broker-a"),
            _fleet_status("broker-b"),
            _fleet_status("broker-c"),
        ],
        approval_granted=True,
    )

    assert result == {
        "mode": "local_simulation_only",
        "state": "ready",
        "decisions": [
            {"broker_id": "broker-a", "stage": "canary", "state": "canary"},
            {"broker_id": "broker-b", "stage": "staged", "state": "staged_rollout"},
            {"broker_id": "broker-c", "stage": "broad", "state": "broad_rollout"},
        ],
        "reasons": [],
    }


def test_rollout_simulator_rejects_incompatible_broker() -> None:
    from mcp_broker.rollout_simulator import simulate_rollout

    result = simulate_rollout(
        bundle=_bundle(),
        fleet_statuses=[_fleet_status("broker-a", schema_version=2)],
        approval_granted=True,
    )

    assert result == {
        "mode": "local_simulation_only",
        "state": "compatibility_rejection",
        "decisions": [],
        "reasons": ["broker-a config schema version 2 outside supported range 1..1"],
    }


def test_rollout_simulator_requests_rollback_on_unhealthy_broker() -> None:
    from mcp_broker.rollout_simulator import simulate_rollout

    result = simulate_rollout(
        bundle=_bundle(),
        fleet_statuses=[_fleet_status("broker-a", status="degraded")],
        approval_granted=True,
    )

    assert result == {
        "mode": "local_simulation_only",
        "state": "rollback",
        "decisions": [
            {"broker_id": "broker-a", "stage": "canary", "state": "rollback"}
        ],
        "reasons": ["broker-a health status degraded triggers rollback"],
    }


def test_rollout_simulator_cli_outputs_local_simulation_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    bundle_path = tmp_path / "bundle.json"
    fleet_path = tmp_path / "fleet.json"
    bundle_path.write_text(json.dumps(_bundle()), encoding="utf-8")
    fleet_path.write_text(json.dumps([_fleet_status("broker-a")]), encoding="utf-8")

    assert (
        cli_main(
            [
                "rollout",
                "simulate",
                "--bundle",
                str(bundle_path),
                "--fleet-status",
                str(fleet_path),
                "--approved",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "local_simulation_only"
    assert payload["decisions"] == [
        {"broker_id": "broker-a", "stage": "canary", "state": "canary"}
    ]
