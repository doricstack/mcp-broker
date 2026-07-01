from __future__ import annotations

import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

REASON = "Emergency rollout bypass for runtime recovery"
OPERATOR = "operator@example.com"
CREATED_AT = "2026-07-01T12:00:00Z"
EXPIRES_AT = "2026-07-01T12:30:00Z"
AFTER_EXPIRATION = "2026-07-01T12:31:00Z"
CLI_EXPIRES_AT = "2099-07-01T12:30:00Z"
BYPASSED_POLICY_PATHS = [
    "policy.rollout.approval",
    "policy.bootstrap.apply",
]


def test_break_glass_create_writes_active_record_pointer_and_audit_journal(
    tmp_path: Path,
) -> None:
    from mcp_broker.break_glass import BreakGlassStore

    state_dir = tmp_path / "state"

    record = BreakGlassStore(state_dir).create(
        reason=REASON,
        operator=OPERATOR,
        expires_at=EXPIRES_AT,
        bypassed_policy_paths=BYPASSED_POLICY_PATHS,
        created_at=CREATED_AT,
    )

    record_path = state_dir / "break-glass" / "records" / f"{record['record_id']}.json"
    active_pointer = json.loads(
        (state_dir / "break-glass" / "active.json").read_text(encoding="utf-8")
    )
    audit_records = [
        json.loads(line)
        for line in (state_dir / "break-glass" / "audit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]

    assert record["status"] == "active"
    assert record["created_at"] == CREATED_AT
    assert record["expires_at"] == EXPIRES_AT
    assert record["reason"] == REASON
    assert record["operator"] == OPERATOR
    assert record["bypassed_policy_paths"] == BYPASSED_POLICY_PATHS
    assert record["audit_path"] == str(state_dir / "break-glass" / "audit.jsonl")
    assert record_path.is_file()
    assert active_pointer == {
        "record_id": record["record_id"],
        "record_path": str(record_path),
    }
    assert audit_records == [
        {
            "event": "break_glass.created",
            "record_id": record["record_id"],
            "operator": OPERATOR,
            "reason": REASON,
            "bypassed_policy_paths": BYPASSED_POLICY_PATHS,
            "expires_at": EXPIRES_AT,
            "ts": CREATED_AT,
        }
    ]


def test_break_glass_rejects_expired_or_incomplete_records(
    tmp_path: Path,
) -> None:
    from mcp_broker.break_glass import BreakGlassError, BreakGlassStore

    store = BreakGlassStore(tmp_path / "state")

    with pytest.raises(BreakGlassError, match="expires_at must be in the future"):
        store.create(
            reason=REASON,
            operator=OPERATOR,
            expires_at=CREATED_AT,
            bypassed_policy_paths=BYPASSED_POLICY_PATHS,
            created_at=CREATED_AT,
        )
    with pytest.raises(BreakGlassError, match="reason is required"):
        store.create(
            reason=" ",
            operator=OPERATOR,
            expires_at=EXPIRES_AT,
            bypassed_policy_paths=BYPASSED_POLICY_PATHS,
            created_at=CREATED_AT,
        )
    with pytest.raises(BreakGlassError, match="operator is required"):
        store.create(
            reason=REASON,
            operator=" ",
            expires_at=EXPIRES_AT,
            bypassed_policy_paths=BYPASSED_POLICY_PATHS,
            created_at=CREATED_AT,
        )
    with pytest.raises(BreakGlassError, match="at least one bypassed policy path"):
        store.create(
            reason=REASON,
            operator=OPERATOR,
            expires_at=EXPIRES_AT,
            bypassed_policy_paths=[],
            created_at=CREATED_AT,
        )


def test_break_glass_status_requires_active_unexpired_record(
    tmp_path: Path,
) -> None:
    from mcp_broker.break_glass import BreakGlassError, BreakGlassStore

    state_dir = tmp_path / "state"
    store = BreakGlassStore(state_dir)
    created = store.create(
        reason=REASON,
        operator=OPERATOR,
        expires_at=EXPIRES_AT,
        bypassed_policy_paths=BYPASSED_POLICY_PATHS,
        created_at=CREATED_AT,
    )

    active_status = store.status(now=CREATED_AT)

    assert active_status["degraded"] is True
    assert active_status["status"] == "active"
    assert active_status["active_record"]["record_id"] == created["record_id"]

    expired_status = store.status(now=AFTER_EXPIRATION)
    assert expired_status == {
        "active_record": None,
        "degraded": False,
        "status": "inactive",
    }
    with pytest.raises(BreakGlassError, match="break-glass record expired"):
        store.require_active_record(now=AFTER_EXPIRATION)


def test_break_glass_cli_create_and_status_emit_sorted_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker import cli

    state_dir = tmp_path / "state"

    assert (
        cli.main(
            [
                "break-glass",
                "create",
                "--state-dir",
                str(state_dir),
                "--reason",
                REASON,
                "--operator",
                OPERATOR,
                "--expires-at",
                CLI_EXPIRES_AT,
                "--bypass-policy",
                BYPASSED_POLICY_PATHS[0],
                "--bypass-policy",
                BYPASSED_POLICY_PATHS[1],
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)

    assert (
        cli.main(
            [
                "break-glass",
                "status",
                "--state-dir",
                str(state_dir),
            ]
        )
        == 0
    )
    status = json.loads(capsys.readouterr().out)

    assert created["status"] == "active"
    assert created["created_at"].endswith("Z")
    assert status["degraded"] is True
    assert status["active_record"]["record_id"] == created["record_id"]
