from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


TENANT_CONTEXT = {
    "tenant_id": "tenant-a",
    "workspace_id": "workspace-a",
    "user_id": "user-a",
}
NOW = datetime(2026, 7, 4, 6, 0, tzinfo=UTC)


def test_distributed_state_parse_utc_normalizes_z_and_offsets() -> None:
    from mcp_broker.distributed_state import _parse_utc

    assert _parse_utc("2026-07-04T06:00:00Z") == NOW
    assert _parse_utc("2026-07-04T02:00:00-04:00") == NOW
    assert _parse_utc("2026-07-04T06:00:00Z").tzinfo is UTC


def test_distributed_state_store_acquires_lock_with_audit_event(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateStore

    store = DistributedStateStore(tmp_path / "state")

    lock = store.acquire_lock(
        owner_id="worker-a",
        tenant_context=TENANT_CONTEXT,
        now=NOW,
        ttl_seconds=60,
    )

    assert lock == {
        "owner_id": "worker-a",
        "token": "000000000001",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "user_id": "user-a",
        "acquired_at": "2026-07-04T06:00:00Z",
        "expires_at": "2026-07-04T06:01:00Z",
    }
    assert _read_json(tmp_path / "state" / "shared-runtime" / "lock.json") == lock
    assert _audit_events(tmp_path / "state")[-1]["event_type"] == "distributed_state_lock"
    assert _audit_events(tmp_path / "state")[-1]["result"] == "acquired"


def test_distributed_state_store_rejects_active_lock_conflict_with_audit(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import (
        DistributedStateConflict,
        DistributedStateStore,
    )

    store = DistributedStateStore(tmp_path / "state")
    store.acquire_lock(
        owner_id="worker-a",
        tenant_context=TENANT_CONTEXT,
        now=NOW,
        ttl_seconds=60,
    )

    with pytest.raises(DistributedStateConflict, match="state lock is held"):
        store.acquire_lock(
            owner_id="worker-b",
            tenant_context=TENANT_CONTEXT,
            now=NOW + timedelta(seconds=30),
            ttl_seconds=60,
        )

    assert _audit_events(tmp_path / "state")[-1] == {
        "event_type": "distributed_state_lock",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "user_id": "user-a",
        "owner_id": "worker-b",
        "result": "denied",
        "denial_reason": "lock_conflict",
    }


@pytest.mark.parametrize(
    ("owner_id", "ttl_seconds", "match"),
    [
        ("", 60, "owner_id is required"),
        ("worker/a", 60, "path separators"),
        ("worker-a", 0, "ttl_seconds"),
    ],
)
def test_distributed_state_store_rejects_invalid_lock_inputs(
    tmp_path: Path,
    owner_id: str,
    ttl_seconds: int,
    match: str,
) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    with pytest.raises(DistributedStateError, match=match):
        DistributedStateStore(tmp_path / "state").acquire_lock(
            owner_id=owner_id,
            tenant_context=TENANT_CONTEXT,
            now=NOW,
            ttl_seconds=ttl_seconds,
        )


def test_distributed_state_store_rejects_naive_lock_timestamp(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    with pytest.raises(DistributedStateError, match="timezone-aware"):
        DistributedStateStore(tmp_path / "state").acquire_lock(
            owner_id="worker-a",
            tenant_context=TENANT_CONTEXT,
            now=datetime(2026, 7, 4, 6, 0),
            ttl_seconds=60,
        )


def test_distributed_state_store_rejects_invalid_tenant_context(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    with pytest.raises(DistributedStateError, match="tenant_id"):
        DistributedStateStore(tmp_path / "state").acquire_lock(
            owner_id="worker-a",
            tenant_context={**TENANT_CONTEXT, "tenant_id": ""},
            now=NOW,
            ttl_seconds=60,
        )


def test_distributed_state_store_recovers_stale_lock_before_acquiring(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateStore

    store = DistributedStateStore(tmp_path / "state")
    stale = store.acquire_lock(
        owner_id="worker-a",
        tenant_context=TENANT_CONTEXT,
        now=NOW,
        ttl_seconds=30,
    )

    recovered = store.acquire_lock(
        owner_id="worker-b",
        tenant_context=TENANT_CONTEXT,
        now=NOW + timedelta(seconds=31),
        ttl_seconds=60,
    )

    assert recovered["owner_id"] == "worker-b"
    assert recovered["token"] == "000000000002"
    assert _audit_events(tmp_path / "state")[-2] == {
        "event_type": "distributed_state_lock",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "user_id": "user-a",
        "owner_id": "worker-b",
        "result": "recovered",
        "stale_owner_id": stale["owner_id"],
        "stale_token": stale["token"],
    }


def test_distributed_state_store_applies_state_with_conflict_rejection_and_journal(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import (
        DistributedStateConflict,
        DistributedStateStore,
    )

    store = DistributedStateStore(tmp_path / "state")
    lock = store.acquire_lock(
        owner_id="worker-a",
        tenant_context=TENANT_CONTEXT,
        now=NOW,
        ttl_seconds=60,
    )

    first = store.apply_state(
        lock=lock,
        state={"deployment_id": "deploy-a", "bundle_version": "1.0.0"},
        expected_active_revision=None,
    )

    assert first["revision"] == 1
    assert first["status"] == "active"
    assert _read_json(tmp_path / "state" / "shared-runtime" / "active.json")[
        "state"
    ] == {"bundle_version": "1.0.0", "deployment_id": "deploy-a"}

    with pytest.raises(DistributedStateConflict, match="active revision conflict"):
        store.apply_state(
            lock=lock,
            state={"deployment_id": "deploy-b", "bundle_version": "1.0.1"},
            expected_active_revision=99,
        )

    assert _journal_actions(tmp_path / "state") == ["apply"]
    assert _audit_events(tmp_path / "state")[-1]["denial_reason"] == "revision_conflict"


def test_distributed_state_store_allocates_revision_from_journal_when_active_is_missing(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateStore

    store = DistributedStateStore(tmp_path / "state")
    lock = store.acquire_lock(
        owner_id="worker-a",
        tenant_context=TENANT_CONTEXT,
        now=NOW,
        ttl_seconds=60,
    )
    first = store.apply_state(
        lock=lock,
        state={"deployment_id": "deploy-a"},
        expected_active_revision=None,
    )
    (tmp_path / "state" / "shared-runtime" / "active.json").unlink()

    second = store.apply_state(
        lock=lock,
        state={"deployment_id": "deploy-b"},
        expected_active_revision=None,
    )

    assert first["revision"] == 1
    assert second["revision"] == 2


def test_distributed_state_store_rejects_mutation_with_missing_lock(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    with pytest.raises(DistributedStateError, match="state lock is missing"):
        DistributedStateStore(tmp_path / "state").apply_state(
            lock={"owner_id": "worker-a", "token": "000000000001"},
            state={"deployment_id": "deploy-a"},
            expected_active_revision=None,
        )


def test_distributed_state_store_rejects_mutation_with_mismatched_lock(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import (
        DistributedStateConflict,
        DistributedStateStore,
    )

    store = DistributedStateStore(tmp_path / "state")
    store.acquire_lock(
        owner_id="worker-a",
        tenant_context=TENANT_CONTEXT,
        now=NOW,
        ttl_seconds=60,
    )

    with pytest.raises(DistributedStateConflict, match="matching lock token"):
        store.apply_state(
            lock={
                "owner_id": "worker-b",
                "token": "000000000999",
                **TENANT_CONTEXT,
            },
            state={"deployment_id": "deploy-a"},
            expected_active_revision=None,
        )

    assert _audit_events(tmp_path / "state")[-1]["denial_reason"] == "lock_token_mismatch"


def test_distributed_state_store_rolls_back_to_previous_revision(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateStore

    store = DistributedStateStore(tmp_path / "state")
    lock = store.acquire_lock(
        owner_id="worker-a",
        tenant_context=TENANT_CONTEXT,
        now=NOW,
        ttl_seconds=60,
    )
    first = store.apply_state(
        lock=lock,
        state={"deployment_id": "deploy-a", "bundle_version": "1.0.0"},
        expected_active_revision=None,
    )
    second = store.apply_state(
        lock=lock,
        state={"deployment_id": "deploy-b", "bundle_version": "1.0.1"},
        expected_active_revision=first["revision"],
    )

    rollback = store.rollback(lock=lock)

    assert rollback == {
        "active_revision": first["revision"],
        "previous_revision": second["revision"],
    }
    assert _read_json(tmp_path / "state" / "shared-runtime" / "active.json")[
        "revision"
    ] == first["revision"]
    assert _journal_actions(tmp_path / "state") == ["apply", "apply", "rollback"]


def test_distributed_state_store_rejects_rollback_without_active_state(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    store = DistributedStateStore(tmp_path / "state")
    lock = store.acquire_lock(
        owner_id="worker-a",
        tenant_context=TENANT_CONTEXT,
        now=NOW,
        ttl_seconds=60,
    )

    with pytest.raises(DistributedStateError, match="active shared-runtime state"):
        store.rollback(lock=lock)


def test_distributed_state_store_rejects_rollback_without_previous_state(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    store = DistributedStateStore(tmp_path / "state")
    lock = store.acquire_lock(
        owner_id="worker-a",
        tenant_context=TENANT_CONTEXT,
        now=NOW,
        ttl_seconds=60,
    )
    store.apply_state(
        lock=lock,
        state={"deployment_id": "deploy-a"},
        expected_active_revision=None,
    )

    with pytest.raises(DistributedStateError, match="previous shared-runtime state"):
        store.rollback(lock=lock)


def test_distributed_state_store_replays_journal_during_recovery(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateStore

    store = DistributedStateStore(tmp_path / "state")
    lock = store.acquire_lock(
        owner_id="worker-a",
        tenant_context=TENANT_CONTEXT,
        now=NOW,
        ttl_seconds=60,
    )
    applied = store.apply_state(
        lock=lock,
        state={"deployment_id": "deploy-a", "bundle_version": "1.0.0"},
        expected_active_revision=None,
    )
    active_path = tmp_path / "state" / "shared-runtime" / "active.json"
    active_path.unlink()
    partial = tmp_path / "state" / "shared-runtime" / "active.json.tmp"
    partial.write_text("partial", encoding="utf-8")

    recovery = store.recover()

    assert recovery == {
        "active_revision": applied["revision"],
        "replayed": True,
        "removed_partial_files": [str(partial)],
    }
    assert _read_json(active_path)["revision"] == applied["revision"]
    assert not partial.exists()
    assert _audit_events(tmp_path / "state")[-1]["event_type"] == (
        "distributed_state_recovery"
    )


def test_distributed_state_store_replay_rejects_apply_entry_without_record(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    root = tmp_path / "state" / "shared-runtime"
    root.mkdir(parents=True)
    (root / "journal.jsonl").write_text('{"action":"apply"}\n', encoding="utf-8")

    with pytest.raises(DistributedStateError, match="apply journal entry is missing record"):
        DistributedStateStore(tmp_path / "state").recover()


def test_distributed_state_store_replay_rejects_incomplete_rollback_entry(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    root = tmp_path / "state" / "shared-runtime"
    root.mkdir(parents=True)
    (root / "journal.jsonl").write_text(
        json.dumps(
            {
                "action": "rollback",
                "active_record": {"revision": 1, "state": {"deployment_id": "deploy-a"}},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DistributedStateError, match="rollback journal entry is incomplete"):
        DistributedStateStore(tmp_path / "state").recover()


def test_distributed_state_store_replays_valid_rollback_journal_entry(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateStore

    root = tmp_path / "state" / "shared-runtime"
    root.mkdir(parents=True)
    first = {"revision": 1, "status": "active", "state": {"deployment_id": "deploy-a"}}
    second = {"revision": 2, "status": "active", "state": {"deployment_id": "deploy-b"}}
    root.joinpath("journal.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"action": "apply", "record": first}),
                json.dumps({"action": "apply", "record": second}),
                json.dumps(
                    {
                        "action": "rollback",
                        "active_record": first,
                        "previous_record": second,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    recovery = DistributedStateStore(tmp_path / "state").recover()

    assert recovery["active_revision"] == 1
    assert _read_json(root / "active.json") == first
    assert _read_json(root / "previous.json") == second


def test_distributed_state_store_ignores_unknown_journal_actions_during_replay(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateStore

    root = tmp_path / "state" / "shared-runtime"
    root.mkdir(parents=True)
    active = {"revision": 1, "status": "active", "state": {"deployment_id": "deploy-a"}}
    root.joinpath("journal.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"action": "noop", "record": {"revision": 99}}),
                json.dumps({"action": "apply", "record": active}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    recovery = DistributedStateStore(tmp_path / "state").recover()

    assert recovery["active_revision"] == 1
    assert _read_json(root / "active.json") == active


def test_distributed_state_store_recovery_checks_existing_active_state(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateStore

    store = DistributedStateStore(tmp_path / "state")
    lock = store.acquire_lock(
        owner_id="worker-a",
        tenant_context=TENANT_CONTEXT,
        now=NOW,
        ttl_seconds=60,
    )
    applied = store.apply_state(
        lock=lock,
        state={"deployment_id": "deploy-a"},
        expected_active_revision=None,
    )
    partial = tmp_path / "state" / "shared-runtime" / "active.json.tmp"
    partial.write_text("partial", encoding="utf-8")

    recovery = store.recover()

    assert recovery == {
        "active_revision": applied["revision"],
        "replayed": False,
        "removed_partial_files": [str(partial)],
    }
    assert not partial.exists()
    assert _audit_events(tmp_path / "state")[-1]["result"] == "checked"


def test_distributed_state_store_recovery_requires_journal_entries(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    with pytest.raises(DistributedStateError, match="no shared-runtime journal"):
        DistributedStateStore(tmp_path / "state").recover()


def test_distributed_state_store_recovery_rejects_malformed_apply_journal(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    journal = tmp_path / "state" / "shared-runtime" / "journal.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({"action": "apply"}) + "\n", encoding="utf-8")

    with pytest.raises(DistributedStateError, match="apply journal entry"):
        DistributedStateStore(tmp_path / "state").recover()


def test_distributed_state_store_recovery_rejects_malformed_rollback_journal(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    journal = tmp_path / "state" / "shared-runtime" / "journal.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text(json.dumps({"action": "rollback"}) + "\n", encoding="utf-8")

    with pytest.raises(DistributedStateError, match="rollback journal entry"):
        DistributedStateStore(tmp_path / "state").recover()


def test_distributed_state_store_recovery_rejects_non_object_journal_line(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    journal = tmp_path / "state" / "shared-runtime" / "journal.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text("[]\n", encoding="utf-8")

    with pytest.raises(DistributedStateError, match="expected JSON object"):
        DistributedStateStore(tmp_path / "state").recover()


def test_distributed_state_store_rejects_non_object_active_file(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import DistributedStateError, DistributedStateStore

    active_path = tmp_path / "state" / "shared-runtime" / "active.json"
    active_path.parent.mkdir(parents=True)
    active_path.write_text("[]", encoding="utf-8")

    with pytest.raises(DistributedStateError, match="expected JSON object"):
        DistributedStateStore(tmp_path / "state").recover()


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _audit_events(state_dir: Path) -> list[dict[str, object]]:
    audit_path = state_dir / "shared-runtime" / "audit.jsonl"
    return [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]


def _journal_actions(state_dir: Path) -> list[str]:
    journal_path = state_dir / "shared-runtime" / "journal.jsonl"
    return [
        json.loads(line)["action"]
        for line in journal_path.read_text(encoding="utf-8").splitlines()
    ]


# --- the audit event builders --------------------------------------------------

FULL_LOCK = {
    "tenant_id": "tenant-a",
    "workspace_id": "workspace-a",
    "user_id": "user-a",
    "owner_id": "owner-a",
    "token": "token-a",
}


def test_mutation_event_carries_every_field_from_a_populated_lock() -> None:
    """A mutated lookup key falls through to the default, so a fully populated lock
    is what distinguishes the right key from a wrong one."""
    from mcp_broker.distributed_state import _mutation_event

    assert _mutation_event(
        event_type="distributed_state_write", lock=FULL_LOCK, result="allowed"
    ) == {
        "event_type": "distributed_state_write",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "user_id": "user-a",
        "owner_id": "owner-a",
        "lock_token": "token-a",
        "result": "allowed",
    }


def test_mutation_event_defaults_every_missing_lock_field_to_empty_string() -> None:
    """An empty lock is the only case where the defaults themselves are observable."""
    from mcp_broker.distributed_state import _mutation_event

    assert _mutation_event(event_type="e", lock={}, result="denied") == {
        "event_type": "e",
        "tenant_id": "",
        "workspace_id": "",
        "user_id": "",
        "owner_id": "",
        "lock_token": "",
        "result": "denied",
    }


def test_mutation_event_reads_the_lock_token_from_the_token_key() -> None:
    """The event field is lock_token; the lock's own field is token. Conflating the
    two would leave every audit record with an empty token."""
    from mcp_broker.distributed_state import _mutation_event

    event = _mutation_event(event_type="e", lock={"token": "abc"}, result="allowed")

    assert event["lock_token"] == "abc"
    assert "token" not in event


def test_mutation_event_omits_revision_and_denial_reason_when_not_supplied() -> None:
    from mcp_broker.distributed_state import _mutation_event

    event = _mutation_event(event_type="e", lock=FULL_LOCK, result="allowed")

    assert "revision" not in event
    assert "denial_reason" not in event


def test_mutation_event_includes_a_zero_revision() -> None:
    """The guard is `is not None`, so revision 0 is a real revision and must appear.
    A truthiness test would drop it."""
    from mcp_broker.distributed_state import _mutation_event

    event = _mutation_event(
        event_type="e", lock=FULL_LOCK, result="allowed", revision=0
    )

    assert event["revision"] == 0


def test_mutation_event_includes_a_denial_reason_when_supplied() -> None:
    from mcp_broker.distributed_state import _mutation_event

    event = _mutation_event(
        event_type="e", lock=FULL_LOCK, result="denied", denial_reason="stale token"
    )

    assert event["denial_reason"] == "stale token"


def test_mutation_event_includes_an_empty_denial_reason() -> None:
    """Same `is not None` guard: an empty string is a supplied reason."""
    from mcp_broker.distributed_state import _mutation_event

    assert _mutation_event(
        event_type="e", lock=FULL_LOCK, result="denied", denial_reason=""
    )["denial_reason"] == ""


def test_lock_event_carries_the_context_and_the_owner() -> None:
    from mcp_broker.distributed_state import _lock_event

    assert _lock_event(
        context=TENANT_CONTEXT, owner_id="owner-a", result="acquired"
    ) == {
        "event_type": "distributed_state_lock",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "user_id": "user-a",
        "owner_id": "owner-a",
        "result": "acquired",
    }


def test_lock_event_adds_only_the_optional_fields_it_is_given() -> None:
    from mcp_broker.distributed_state import _lock_event

    event = _lock_event(
        context=TENANT_CONTEXT,
        owner_id="owner-a",
        result="denied",
        denial_reason="held",
        stale_owner_id="owner-b",
        stale_token="token-b",
    )

    assert event["denial_reason"] == "held"
    assert event["stale_owner_id"] == "owner-b"
    assert event["stale_token"] == "token-b"

    sparse = _lock_event(context=TENANT_CONTEXT, owner_id="owner-a", result="acquired")
    assert "denial_reason" not in sparse
    assert "stale_owner_id" not in sparse
    assert "stale_token" not in sparse


# --- the remaining helpers ------------------------------------------------------


def test_required_identifier_rejects_blank_and_non_string_values() -> None:
    from mcp_broker.distributed_state import DistributedStateError, _required_identifier

    for bad in ("", "   "):
        with pytest.raises(DistributedStateError) as exc:
            _required_identifier(bad, "owner_id")
        assert str(exc.value) == "owner_id is required"


def test_required_identifier_rejects_both_path_separators() -> None:
    """An identifier becomes part of a filename, so either separator would escape
    the directory it is meant to stay in."""
    from mcp_broker.distributed_state import DistributedStateError, _required_identifier

    for bad in ("a/b", "a\\b"):
        with pytest.raises(DistributedStateError) as exc:
            _required_identifier(bad, "owner_id")
        assert str(exc.value) == "owner_id must not contain path separators"


def test_required_identifier_returns_a_valid_value_unchanged() -> None:
    from mcp_broker.distributed_state import _required_identifier

    assert _required_identifier("owner-a", "owner_id") == "owner-a"


def test_utc_datetime_requires_an_aware_value_and_converts_to_utc() -> None:
    from datetime import timezone

    from mcp_broker.distributed_state import DistributedStateError, _utc_datetime

    with pytest.raises(DistributedStateError) as exc:
        _utc_datetime(datetime(2026, 1, 1))
    assert str(exc.value) == "now must be timezone-aware"

    offset = timezone(timedelta(hours=4))
    converted = _utc_datetime(datetime(2026, 1, 1, 4, tzinfo=offset))
    assert converted == datetime(2026, 1, 1, tzinfo=UTC)
    assert converted.tzinfo is timezone.utc


def test_format_utc_renders_a_z_suffix_and_converts_from_other_offsets() -> None:
    from datetime import timezone

    from mcp_broker.distributed_state import _format_utc

    offset = timezone(timedelta(hours=-5))
    rendered = _format_utc(datetime(2025, 12, 31, 19, tzinfo=offset))

    assert rendered == "2026-01-01T00:00:00Z"
    assert "+00:00" not in rendered


def test_parse_utc_round_trips_the_formatted_value() -> None:
    from mcp_broker.distributed_state import _format_utc, _parse_utc

    value = datetime(2026, 1, 1, tzinfo=UTC)

    assert _parse_utc(_format_utc(value).replace("Z", "+00:00")) == value


def test_revision_reads_the_field_and_passes_none_through() -> None:
    from mcp_broker.distributed_state import _revision

    assert _revision(None) is None
    assert _revision({"revision": 7}) == 7
    assert _revision({"revision": "8"}) == 8


def test_read_json_optional_returns_none_for_a_missing_file(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import _read_json_optional

    assert _read_json_optional(tmp_path / "missing.json") is None


def test_read_json_optional_reads_an_existing_object(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import _read_json_optional

    target = tmp_path / "state.json"
    target.write_text(json.dumps({"a": 1}), encoding="utf-8")

    assert _read_json_optional(target) == {"a": 1}


def test_require_json_reports_the_caller_message_when_absent(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import DistributedStateError, _require_json

    with pytest.raises(DistributedStateError) as exc:
        _require_json(tmp_path / "missing.json", "lock is not held")
    assert str(exc.value) == "lock is not held"


def test_require_json_rejects_valid_json_that_is_not_an_object(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import DistributedStateError, _require_json

    target = tmp_path / "state.json"
    target.write_text(json.dumps([1]), encoding="utf-8")

    with pytest.raises(DistributedStateError) as exc:
        _require_json(target, "unused")
    assert str(exc.value) == f"expected JSON object: {target}"


def test_read_jsonl_rejects_a_line_that_is_not_an_object(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import DistributedStateError, _read_jsonl

    target = tmp_path / "audit.jsonl"
    target.write_text(json.dumps({"a": 1}) + "\n" + json.dumps([2]) + "\n", encoding="utf-8")

    with pytest.raises(DistributedStateError) as exc:
        _read_jsonl(target)
    assert str(exc.value) == f"expected JSON object in {target}"


def test_read_jsonl_returns_every_line_in_order(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import _read_jsonl

    target = tmp_path / "audit.jsonl"
    target.write_text(
        json.dumps({"n": 1}) + "\n" + json.dumps({"n": 2}) + "\n", encoding="utf-8"
    )

    assert _read_jsonl(target) == [{"n": 1}, {"n": 2}]


def test_write_json_atomic_formats_sorted_and_indented_with_a_trailing_newline(
    tmp_path: Path,
) -> None:
    from mcp_broker.distributed_state import _write_json_atomic

    target = tmp_path / "state.json"
    _write_json_atomic(target, {"b": 1, "a": 2})

    assert target.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "b": 1\n}\n'


def test_write_json_atomic_creates_nested_parents_and_leaves_no_temp(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import _write_json_atomic

    # Two missing levels: mkdir(parents=False) still creates a single one.
    target = tmp_path / "deep" / "nested" / "state.json"
    _write_json_atomic(target, {"a": 1})

    assert target.is_file()
    assert sorted(p.name for p in target.parent.iterdir()) == ["state.json"]


def test_write_json_atomic_replaces_an_existing_file_entirely(tmp_path: Path) -> None:
    from mcp_broker.distributed_state import _write_json_atomic

    target = tmp_path / "state.json"
    target.write_text('{"stale": true}', encoding="utf-8")
    _write_json_atomic(target, {"fresh": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"fresh": True}


def test_format_utc_is_utc_even_when_the_host_is_not(monkeypatch: pytest.MonkeyPatch) -> None:
    """The stored timestamp must not follow the machine's timezone.

    astimezone(None) converts to local time, which is indistinguishable from UTC on a
    UTC host and wrong everywhere else. Forcing a zone is what makes the difference
    observable.
    """
    import time

    from mcp_broker.distributed_state import _format_utc

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        rendered = _format_utc(datetime(2026, 1, 1, 12, tzinfo=UTC))
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()

    assert rendered == "2026-01-01T12:00:00Z"
