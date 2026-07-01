from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support.bundles import write_signed_bundle


pytestmark = pytest.mark.unit


def test_deployment_store_records_active_and_previous_pointers(tmp_path: Path) -> None:
    from mcp_broker.deployments import DeploymentStore

    state_dir = tmp_path / "runtime" / "state"
    first_bundle = write_signed_bundle(tmp_path / "first.json")
    second_bundle = write_signed_bundle(
        tmp_path / "second.json",
        {
            **_minimal_bundle("team-local", "2026.07.02"),
            "upstreams": {
                "catalog-cache": {
                    "enabled": True,
                    "mode": "shared",
                    "transport": "stdio",
                    "command": "catalog-cache-server",
                    "profiles": ["codex"],
                },
            },
        },
    )

    store = DeploymentStore(state_dir)
    first = store.record_deployment(first_bundle)
    second = store.record_deployment(second_bundle)

    assert first["deployment_id"] != second["deployment_id"]
    assert _read_json(state_dir / "deployments" / "active.json") == {
        "deployment_id": second["deployment_id"],
        "record_path": str(state_dir / "deployments" / "records" / f"{second['deployment_id']}.json"),
    }
    assert _read_json(state_dir / "deployments" / "previous.json") == {
        "deployment_id": first["deployment_id"],
        "record_path": str(state_dir / "deployments" / "records" / f"{first['deployment_id']}.json"),
    }
    assert _read_json(Path(second["record_path"]))["status"] == "active"
    assert _journal_actions(state_dir) == ["activate", "activate"]


def test_deployment_store_rolls_back_to_previous_deployment(tmp_path: Path) -> None:
    from mcp_broker.deployments import DeploymentStore

    state_dir = tmp_path / "runtime" / "state"
    store = DeploymentStore(state_dir)
    first = store.record_deployment(write_signed_bundle(tmp_path / "first.json"))
    second = store.record_deployment(
        write_signed_bundle(tmp_path / "second.json", _minimal_bundle("team-local", "2026.07.02"))
    )

    rollback = store.rollback()

    assert rollback["active_deployment_id"] == first["deployment_id"]
    assert rollback["previous_deployment_id"] == second["deployment_id"]
    assert _read_json(state_dir / "deployments" / "active.json")["deployment_id"] == first["deployment_id"]
    assert _read_json(state_dir / "deployments" / "previous.json")["deployment_id"] == second["deployment_id"]
    assert _journal_actions(state_dir) == ["activate", "activate", "rollback"]


def test_deployment_store_recovers_from_partial_pointer_write(tmp_path: Path) -> None:
    from mcp_broker.deployments import DeploymentStore

    state_dir = tmp_path / "runtime" / "state"
    store = DeploymentStore(state_dir)
    first = store.record_deployment(write_signed_bundle(tmp_path / "first.json"))
    deployments_dir = state_dir / "deployments"
    (deployments_dir / "active.json").write_text(
        json.dumps(
            {
                "deployment_id": "missing-deployment",
                "record_path": str(deployments_dir / "records" / "missing-deployment.json"),
            }
        ),
        encoding="utf-8",
    )
    partial = deployments_dir / "active.json.tmp"
    partial.write_text("partial", encoding="utf-8")

    recovery = store.recover()

    assert recovery == {
        "active_deployment_id": first["deployment_id"],
        "recovered": True,
        "removed_partial_files": [str(partial)],
    }
    assert not partial.exists()
    assert _read_json(deployments_dir / "active.json")["deployment_id"] == first["deployment_id"]
    assert _journal_actions(state_dir) == ["activate", "recover"]


def _minimal_bundle(bundle_id: str, version: str) -> dict[str, object]:
    from tests.support.bundles import minimal_bundle

    bundle = minimal_bundle()
    bundle["bundle_id"] = bundle_id
    bundle["version"] = version
    return bundle


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _journal_actions(state_dir: Path) -> list[str]:
    journal = state_dir / "deployments" / "rollback-journal.jsonl"
    return [json.loads(line)["action"] for line in journal.read_text(encoding="utf-8").splitlines()]
