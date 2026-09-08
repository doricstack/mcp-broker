from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys

import pytest

from mcp_broker.cli import main as cli_main


pytestmark = [pytest.mark.unit]

CREATED_AT = "2026-07-04T06:00:00Z"
EXPIRES_AT = "2026-07-04T06:30:00Z"
ACTION_IDS = ["0001-broker-a-canary", "0002-broker-b-staged"]
POLICY_PATHS = ["policy.rollout.approval", "policy.bootstrap.apply"]


def test_governance_approval_records_rollout_targets_without_mutation(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_approval import create_approval

    state_dir = tmp_path / "state"

    approval = create_approval(
        state_dir=state_dir,
        request_type="rollout",
        operator="release-operator",
        reason="approve staged rollout",
        expires_at=EXPIRES_AT,
        action_ids=ACTION_IDS,
        policy_paths=[],
        break_glass_record_id=None,
        created_at=CREATED_AT,
    )

    record_path = Path(str(approval["record_path"]))
    audit_path = state_dir / "governance-approvals" / "audit.jsonl"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    audit_records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

    assert approval["schema_version"] == 1
    assert approval["request_type"] == "rollout"
    assert approval["approved"] is True
    assert approval["changed_runtime_state"] is False
    assert approval["requires_apply_step"] is True
    assert record["operator"] == "release-operator"
    assert record["reason"] == "approve staged rollout"
    assert record["expires_at"] == EXPIRES_AT
    assert record["target"] == {"action_ids": ACTION_IDS}
    assert record["changed_runtime_state"] is False
    assert audit_records == [
        {
            "approval_id": approval["approval_id"],
            "event": "governance_approval.created",
            "operator": "release-operator",
            "request_type": "rollout",
            "target": {"action_ids": ACTION_IDS},
            "ts": CREATED_AT,
        }
    ]


def test_governance_approval_records_policy_override_and_break_glass_targets(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_approval import create_approval

    policy_approval = create_approval(
        state_dir=tmp_path / "state",
        request_type="policy_override",
        operator="release-operator",
        reason="approve temporary policy override",
        expires_at=EXPIRES_AT,
        action_ids=[],
        policy_paths=POLICY_PATHS,
        break_glass_record_id=None,
        created_at=CREATED_AT,
    )
    break_glass_approval = create_approval(
        state_dir=tmp_path / "state",
        request_type="break_glass",
        operator="release-operator",
        reason="approve emergency break-glass record",
        expires_at=EXPIRES_AT,
        action_ids=[],
        policy_paths=[],
        break_glass_record_id="break-glass-abc123",
        created_at="2026-07-04T06:05:00Z",
    )

    policy_record = json.loads(Path(str(policy_approval["record_path"])).read_text(encoding="utf-8"))
    break_glass_record = json.loads(
        Path(str(break_glass_approval["record_path"])).read_text(encoding="utf-8")
    )
    assert policy_record["target"] == {"policy_paths": POLICY_PATHS}
    assert break_glass_record["target"] == {"break_glass_record_id": "break-glass-abc123"}


def test_governance_approval_defaults_created_at_when_not_supplied(tmp_path: Path) -> None:
    from mcp_broker.governance_approval import create_approval

    approval = create_approval(
        state_dir=tmp_path / "state",
        request_type="rollout",
        operator="release-operator",
        reason="approve staged rollout",
        expires_at="2099-07-04T06:30:00Z",
        action_ids=ACTION_IDS,
        policy_paths=[],
        break_glass_record_id=None,
        created_at=None,
    )

    record = json.loads(Path(str(approval["record_path"])).read_text(encoding="utf-8"))

    assert isinstance(record["created_at"], str)
    assert str(record["created_at"]).endswith("Z")


def test_governance_approval_rejects_missing_target_and_expired_approval(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_approval import GovernanceApprovalError, create_approval

    with pytest.raises(GovernanceApprovalError, match="at least one action id"):
        create_approval(
            state_dir=tmp_path / "state",
            request_type="rollback",
            operator="release-operator",
            reason="approve rollback",
            expires_at=EXPIRES_AT,
            action_ids=[],
            policy_paths=[],
            break_glass_record_id=None,
            created_at=CREATED_AT,
        )
    with pytest.raises(GovernanceApprovalError, match="expires_at must be in the future"):
        create_approval(
            state_dir=tmp_path / "state",
            request_type="rollout",
            operator="release-operator",
            reason="approve staged rollout",
            expires_at=CREATED_AT,
            action_ids=ACTION_IDS,
            policy_paths=[],
            break_glass_record_id=None,
            created_at=CREATED_AT,
        )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"request_type": "unknown"}, "unsupported request_type"),
        ({"operator": " "}, "operator is required"),
        ({"reason": " "}, "reason is required"),
        ({"expires_at": "not-a-date"}, "invalid timestamp"),
        ({"expires_at": "2026-07-04T06:30:00"}, "timestamp must include timezone"),
        ({"action_ids": ["bad/id"]}, "invalid action id"),
        ({"request_type": "policy_override", "action_ids": [], "policy_paths": []}, "policy path"),
        (
            {
                "request_type": "policy_override",
                "action_ids": [],
                "policy_paths": ["policy/override"],
            },
            "invalid policy path",
        ),
        (
            {
                "request_type": "break_glass",
                "action_ids": [],
                "break_glass_record_id": None,
            },
            "break_glass_record_id is required",
        ),
        (
            {
                "request_type": "break_glass",
                "action_ids": [],
                "break_glass_record_id": "bad/id",
            },
            "invalid break_glass_record_id",
        ),
    ],
)
def test_governance_approval_rejects_invalid_fields(
    tmp_path: Path,
    kwargs: dict[str, object],
    message: str,
) -> None:
    from mcp_broker.governance_approval import GovernanceApprovalError, create_approval

    args = {
        "state_dir": tmp_path / "state",
        "request_type": "rollout",
        "operator": "release-operator",
        "reason": "approve staged rollout",
        "expires_at": EXPIRES_AT,
        "action_ids": ACTION_IDS,
        "policy_paths": [],
        "break_glass_record_id": None,
        "created_at": CREATED_AT,
    }
    args.update(kwargs)

    with pytest.raises(GovernanceApprovalError, match=message):
        create_approval(**args)


def test_governance_approval_target_builder_rejects_unknown_request_type() -> None:
    from mcp_broker.governance_approval import GovernanceApprovalError, _target_for_request

    with pytest.raises(GovernanceApprovalError, match="unsupported request_type"):
        _target_for_request(
            request_type="unknown",
            action_ids=[],
            policy_paths=[],
            break_glass_record_id=None,
        )


def test_governance_approval_policy_paths_requires_at_least_one_path() -> None:
    from mcp_broker.governance_approval import GovernanceApprovalError, _policy_paths

    with pytest.raises(GovernanceApprovalError) as exc_info:
        _policy_paths([])
    assert str(exc_info.value) == "at least one policy path is required"


def test_governance_approval_rejects_duplicate_record(tmp_path: Path) -> None:
    from mcp_broker.governance_approval import GovernanceApprovalError, create_approval

    args = {
        "state_dir": tmp_path / "state",
        "request_type": "rollout",
        "operator": "release-operator",
        "reason": "approve staged rollout",
        "expires_at": EXPIRES_AT,
        "action_ids": ACTION_IDS,
        "policy_paths": [],
        "break_glass_record_id": None,
        "created_at": CREATED_AT,
    }

    create_approval(**args)
    with pytest.raises(GovernanceApprovalError, match="approval record already exists"):
        create_approval(**args)


def test_governance_approval_cli_emits_record_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        cli_main(
            [
                "governance",
                "approve",
                "--state-dir",
                str(tmp_path / "state"),
                "--request-type",
                "rollout",
                "--operator",
                "release-operator",
                "--reason",
                "approve staged rollout",
                "--expires-at",
                EXPIRES_AT,
                "--action-id",
                ACTION_IDS[0],
                "--created-at",
                CREATED_AT,
            ]
        )
        == 0
    )

    stdout = capsys.readouterr().out
    assert "governance approval recorded:" in stdout
    assert "record=" in stdout


def test_governance_approval_direct_cli_reports_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.governance_approval import main

    assert (
        main(
            [
                "--state-dir",
                str(tmp_path / "state"),
                "--request-type",
                "rollout",
                "--operator",
                "release-operator",
                "--reason",
                "approve staged rollout",
                "--expires-at",
                CREATED_AT,
                "--action-id",
                ACTION_IDS[0],
                "--created-at",
                CREATED_AT,
            ]
        )
        == 1
    )

    assert "expires_at must be in the future" in capsys.readouterr().out


def test_governance_approval_main_forwards_all_fields_and_emits_exact_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import governance_approval

    calls: list[dict[str, object]] = []
    record_path = tmp_path / "approval.json"

    def create_approval(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        return {"approval_id": "approval-123", "record_path": record_path}

    monkeypatch.setattr(governance_approval, "create_approval", create_approval)

    state_dir = tmp_path / "state"
    assert governance_approval.main(
        [
            "--state-dir",
            str(state_dir),
            "--request-type",
            "policy_override",
            "--operator",
            "release-operator",
            "--reason",
            "approve policy override",
            "--expires-at",
            EXPIRES_AT,
            "--action-id",
            "action-a",
            "--policy-path",
            "policy.alpha",
            "--break-glass-record-id",
            "break-glass-123",
            "--created-at",
            CREATED_AT,
        ]
    ) == 0
    assert calls == [
        {
            "state_dir": state_dir,
            "request_type": "policy_override",
            "operator": "release-operator",
            "reason": "approve policy override",
            "expires_at": EXPIRES_AT,
            "action_ids": ["action-a"],
            "policy_paths": ["policy.alpha"],
            "break_glass_record_id": "break-glass-123",
            "created_at": CREATED_AT,
        }
    ]
    assert capsys.readouterr().out == (
        f"governance approval recorded: approval-123 record={record_path}\n"
    )


@pytest.mark.error_simulation
def test_governance_approval_module_entrypoint_exits_with_main_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "governance_approval",
            "--state-dir",
            str(tmp_path / "state"),
            "--request-type",
            "rollout",
            "--operator",
            "release-operator",
            "--reason",
            "approve staged rollout",
            "--expires-at",
            EXPIRES_AT,
            "--action-id",
            ACTION_IDS[0],
            "--created-at",
            CREATED_AT,
        ],
    )

    module_name = "mcp_broker.governance_approval"
    previous_module = sys.modules.pop(module_name, None)

    try:
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_module(module_name, run_name="__main__")
    finally:
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module

    assert exit_info.value.code == 0


def test_governance_approval_parser_has_exact_public_contract() -> None:
    from mcp_broker.governance_approval import _parser

    parser = _parser()
    assert parser.description == "Record local governance approval"
    actions = {action.dest: action for action in parser._actions}
    assert set(actions) == {
        "help",
        "state_dir",
        "request_type",
        "operator",
        "reason",
        "expires_at",
        "action_id",
        "policy_path",
        "break_glass_record_id",
        "created_at",
    }
    for name in {"state_dir", "request_type", "operator", "reason", "expires_at"}:
        assert actions[name].required is True
    for name in {"action_id", "policy_path", "break_glass_record_id", "created_at"}:
        assert actions[name].required is False
    assert actions["state_dir"].type is Path
    assert actions["action_id"].default == []
    assert actions["policy_path"].default == []
    assert actions["action_id"].const is None
    assert actions["policy_path"].const is None

    parsed = parser.parse_args(
        [
            "--state-dir",
            "state",
            "--request-type",
            "rollout",
            "--operator",
            "operator",
            "--reason",
            "reason",
            "--expires-at",
            EXPIRES_AT,
            "--action-id",
            "action-one",
            "--action-id",
            "action-two",
            "--policy-path",
            "policy/one",
            "--policy-path",
            "policy/two",
        ]
    )
    assert parsed.action_id == ["action-one", "action-two"]
    assert parsed.policy_path == ["policy/one", "policy/two"]


# --- the approval record, the summary, and the audit line ----------------------


def _create(tmp_path: Path, **overrides: object) -> dict[str, object]:
    from mcp_broker.governance_approval import create_approval

    kwargs: dict[str, object] = {
        "state_dir": tmp_path,
        "request_type": "rollout",
        "operator": "operator@example.com",
        "reason": "Staged rollout approval",
        "expires_at": EXPIRES_AT,
        "action_ids": ACTION_IDS,
        "policy_paths": POLICY_PATHS,
        "break_glass_record_id": None,
        "created_at": CREATED_AT,
    }
    kwargs.update(overrides)
    return create_approval(**kwargs)


def test_create_approval_returns_the_full_summary(tmp_path: Path) -> None:
    """The summary is the caller's whole view of the approval, so every key and
    every boolean in it is part of the contract."""
    summary = _create(tmp_path)

    approval_dir = tmp_path / "governance-approvals"
    assert summary == {
        "schema_version": 1,
        "approval_id": summary["approval_id"],
        "approved": True,
        "request_type": "rollout",
        "record_path": str(approval_dir / "records" / f"{summary['approval_id']}.json"),
        "audit_path": str(approval_dir / "audit.jsonl"),
        "requires_apply_step": True,
        "changed_runtime_state": False,
    }


def test_create_approval_writes_the_full_record(tmp_path: Path) -> None:
    """requires_apply_step and changed_runtime_state are governance claims: the
    first says the approval does not apply itself, the second says it touched no
    runtime state. Either one flipped misreports what happened."""
    summary = _create(tmp_path)

    approval_dir = tmp_path / "governance-approvals"
    record = json.loads(
        (approval_dir / "records" / f"{summary['approval_id']}.json").read_text(
            encoding="utf-8"
        )
    )

    assert record == {
        "schema_version": 1,
        "approval_id": summary["approval_id"],
        "approved": True,
        "created_at": CREATED_AT,
        "expires_at": EXPIRES_AT,
        "operator": "operator@example.com",
        "reason": "Staged rollout approval",
        "request_type": "rollout",
        "target": {"action_ids": ACTION_IDS},
        "requires_apply_step": True,
        "changed_runtime_state": False,
        "audit_path": str(approval_dir / "audit.jsonl"),
    }


def test_create_approval_writes_one_audit_line_with_the_created_event(
    tmp_path: Path,
) -> None:
    summary = _create(tmp_path)

    audit = (tmp_path / "governance-approvals" / "audit.jsonl").read_text(
        encoding="utf-8"
    )

    assert audit.endswith("\n")
    lines = audit.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "approval_id": summary["approval_id"],
        "event": "governance_approval.created",
        "operator": "operator@example.com",
        "request_type": "rollout",
        "target": {"action_ids": ACTION_IDS},
        "ts": CREATED_AT,
    }


def test_create_approval_appends_rather_than_replacing_the_audit(tmp_path: Path) -> None:
    """Append mode is the point of an audit file: a second approval must not erase
    the first."""
    first = _create(tmp_path)
    second = _create(tmp_path, reason="A second, different approval")

    lines = (tmp_path / "governance-approvals" / "audit.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()

    assert len(lines) == 2
    assert json.loads(lines[0])["approval_id"] == first["approval_id"]
    assert json.loads(lines[1])["approval_id"] == second["approval_id"]


def test_audit_lines_are_compact_and_key_sorted(tmp_path: Path) -> None:
    """The JSONL contract: one compact object per line, keys sorted, no spaces after
    the separators. Anything else changes what downstream readers parse."""
    _create(tmp_path)

    line = (tmp_path / "governance-approvals" / "audit.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()[0]

    assert '", "' not in line, "separators must be compact"
    assert '": "' not in line, "separators must be compact"
    parsed = json.loads(line)
    assert list(parsed) == sorted(parsed), "audit keys must be sorted"


def test_create_approval_gives_different_ids_to_different_approvals(
    tmp_path: Path,
) -> None:
    """The id hashes the seed, so a different reason is a different approval."""
    first = _create(tmp_path)
    second = _create(tmp_path, reason="A second, different approval")

    assert first["approval_id"] != second["approval_id"]


def test_create_approval_gives_the_same_id_to_an_identical_approval(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_approval import _approval_id

    seed = {
        "approved": True,
        "created_at": CREATED_AT,
        "expires_at": EXPIRES_AT,
        "operator": "operator@example.com",
        "reason": "Staged rollout approval",
        "request_type": "rollout",
        "target": {"action_ids": ACTION_IDS},
    }

    assert _create(tmp_path)["approval_id"] == _approval_id(seed)


def test_approval_id_ignores_key_order_but_not_values() -> None:
    from mcp_broker.governance_approval import _approval_id

    assert _approval_id({"a": 1, "b": 2}) == _approval_id({"b": 2, "a": 1})
    assert _approval_id({"a": 1}) != _approval_id({"a": 2})


def test_write_json_new_refuses_to_overwrite_an_existing_record(tmp_path: Path) -> None:
    """An approval record is written once. Overwriting one would rewrite history."""
    from mcp_broker.governance_approval import _write_json_new

    target = tmp_path / "record.json"
    _write_json_new(target, {"a": 1})

    with pytest.raises(Exception):
        _write_json_new(target, {"a": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


def test_write_json_new_creates_nested_parents(tmp_path: Path) -> None:
    from mcp_broker.governance_approval import _write_json_new

    # Two missing levels: mkdir(parents=False) still creates a single one.
    target = tmp_path / "deep" / "nested" / "record.json"
    _write_json_new(target, {"a": 1})

    assert target.is_file()


# --- error messages, id derivation, timestamps and the on-disk formats ---------


def test_target_for_request_requires_at_least_one_action_id() -> None:
    from mcp_broker.governance_approval import (
        GovernanceApprovalError,
        _target_for_request,
    )

    with pytest.raises(GovernanceApprovalError) as exc:
        _target_for_request(
            request_type="rollout",
            action_ids=[],
            policy_paths=[],
            break_glass_record_id=None,
        )
    assert str(exc.value) == "at least one action id is required"


def test_require_future_expiration_message_is_exact() -> None:
    from mcp_broker.governance_approval import (
        GovernanceApprovalError,
        _require_future_expiration,
    )

    with pytest.raises(GovernanceApprovalError) as exc:
        _require_future_expiration("2020-01-01T00:00:00Z", now="2026-01-01T00:00:00Z")
    assert str(exc.value) == "expires_at must be in the future"


def test_approval_id_matches_a_known_digest_for_a_known_seed() -> None:
    """A golden value pins the canonical encoding and the truncation length. Change
    either and every previously issued approval id stops matching."""
    import hashlib

    from mcp_broker.governance_approval import _approval_id

    seed = {"operator": "operator@example.com", "request_type": "rollout"}
    canonical = json.dumps(seed, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    record_id = _approval_id(seed)

    assert record_id == f"governance-approval-{digest}"
    assert len(record_id) == len("governance-approval-") + 16
    # A default-separator encoding hashes differently, so the compact form matters.
    assert canonical != json.dumps(seed, sort_keys=True)


def test_parse_timestamp_accepts_a_capital_z_and_rejects_a_lowercase_one() -> None:
    """The suffix the stored format uses is capital Z; a lowercase z is not ISO and
    must not be silently accepted."""
    from datetime import datetime, timezone

    from mcp_broker.governance_approval import _parse_timestamp

    assert _parse_timestamp("2026-07-04T06:00:00Z") == datetime(
        2026, 7, 4, 6, tzinfo=timezone.utc
    )
    with pytest.raises(Exception):
        _parse_timestamp("2026-07-04T06:00:00z")


def test_parse_timestamp_returns_utc_even_when_the_host_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """astimezone(None) follows the host's local zone, which is indistinguishable
    from UTC on a UTC host and wrong everywhere else."""
    import time
    from datetime import timezone

    from mcp_broker.governance_approval import _parse_timestamp

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        parsed = _parse_timestamp("2026-07-04T06:00:00Z")
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()

    assert parsed.utcoffset() == timezone.utc.utcoffset(None)
    assert parsed.isoformat() == "2026-07-04T06:00:00+00:00"


def test_write_json_new_formats_sorted_and_indented_with_a_trailing_newline(
    tmp_path: Path,
) -> None:
    """The record is read back by other tools and diffed by humans, so indent width,
    key order and the trailing newline are all part of the format."""
    from mcp_broker.governance_approval import _write_json_new

    target = tmp_path / "record.json"
    _write_json_new(target, {"b": 1, "a": 2})

    assert target.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "b": 1\n}\n'


def test_append_audit_creates_nested_parents(tmp_path: Path) -> None:
    from mcp_broker.governance_approval import _append_audit

    # Two missing levels: mkdir(parents=False) still creates a single one.
    target = tmp_path / "deep" / "nested" / "audit.jsonl"
    _append_audit(target, {"a": 1})

    assert target.is_file()


def test_append_audit_sorts_keys_in_a_line_that_is_not_already_sorted(
    tmp_path: Path,
) -> None:
    """The created-event entry happens to be alphabetical already, so asserting
    sorted keys on it cannot fail. An unsorted mapping is what makes sort_keys
    observable."""
    from mcp_broker.governance_approval import _append_audit

    target = tmp_path / "audit.jsonl"
    _append_audit(target, {"zebra": 1, "apple": 2, "mango": 3})

    line = target.read_text(encoding="utf-8").splitlines()[0]

    assert line == '{"apple":2,"mango":3,"zebra":1}'


def test_append_audit_writes_one_compact_line_per_entry(tmp_path: Path) -> None:
    from mcp_broker.governance_approval import _append_audit

    target = tmp_path / "audit.jsonl"
    _append_audit(target, {"a": 1})
    _append_audit(target, {"b": 2})

    assert target.read_text(encoding="utf-8") == '{"a":1}\n{"b":2}\n'
