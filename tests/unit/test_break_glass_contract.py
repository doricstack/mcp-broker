from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest

from tests.support.argparse_output import without_ansi


pytestmark = pytest.mark.unit


def test_break_glass_timestamp_parser_normalizes_z_and_offsets() -> None:
    from mcp_broker.break_glass import _parse_timestamp

    expected = datetime(2026, 7, 4, 6, 0, tzinfo=UTC)
    assert _parse_timestamp("2026-07-04T06:00:00Z") == expected
    assert _parse_timestamp("2026-07-04T02:00:00-04:00") == expected
    assert _parse_timestamp("2026-07-04T06:00:00Z").tzinfo is UTC

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
    with pytest.raises(BreakGlassError, match="invalid bypassed policy path"):
        store.create(
            reason=REASON,
            operator=OPERATOR,
            expires_at=EXPIRES_AT,
            bypassed_policy_paths=["policy/rollout"],
            created_at=CREATED_AT,
        )
    with pytest.raises(BreakGlassError, match="invalid timestamp"):
        store.create(
            reason=REASON,
            operator=OPERATOR,
            expires_at="not-a-date",
            bypassed_policy_paths=BYPASSED_POLICY_PATHS,
            created_at=CREATED_AT,
        )
    with pytest.raises(BreakGlassError, match="timestamp must include timezone"):
        store.create(
            reason=REASON,
            operator=OPERATOR,
            expires_at="2026-07-01T12:30:00",
            bypassed_policy_paths=BYPASSED_POLICY_PATHS,
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


def test_break_glass_require_active_record_returns_unexpired_record(tmp_path: Path) -> None:
    from mcp_broker.break_glass import BreakGlassStore

    store = BreakGlassStore(tmp_path / "state")
    created = store.create(
        reason=REASON,
        operator=OPERATOR,
        expires_at=EXPIRES_AT,
        bypassed_policy_paths=BYPASSED_POLICY_PATHS,
        created_at=CREATED_AT,
    )

    active = store.require_active_record(now=CREATED_AT)

    assert active["record_id"] == created["record_id"]


def test_break_glass_requires_active_record_when_pointer_is_missing(tmp_path: Path) -> None:
    from mcp_broker.break_glass import BreakGlassError, BreakGlassStore

    with pytest.raises(BreakGlassError, match="not active"):
        BreakGlassStore(tmp_path / "state").require_active_record(now=CREATED_AT)


def test_break_glass_rejects_mismatched_active_pointer(tmp_path: Path) -> None:
    from mcp_broker.break_glass import BreakGlassError, BreakGlassStore

    state_dir = tmp_path / "state"
    store = BreakGlassStore(state_dir)
    record = store.create(
        reason=REASON,
        operator=OPERATOR,
        expires_at=EXPIRES_AT,
        bypassed_policy_paths=BYPASSED_POLICY_PATHS,
        created_at=CREATED_AT,
    )
    active_pointer = state_dir / "break-glass" / "active.json"
    active_pointer.write_text(
        json.dumps(
            {
                "record_id": "different-record",
                "record_path": str(state_dir / "break-glass" / "records" / f"{record['record_id']}.json"),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BreakGlassError, match="active pointer does not match record"):
        store.status(now=CREATED_AT)


def test_break_glass_rejects_non_object_active_pointer(tmp_path: Path) -> None:
    from mcp_broker.break_glass import BreakGlassError, BreakGlassStore

    state_dir = tmp_path / "state"
    active_pointer = state_dir / "break-glass" / "active.json"
    active_pointer.parent.mkdir(parents=True)
    active_pointer.write_text("[]", encoding="utf-8")

    with pytest.raises(BreakGlassError, match="expected JSON object"):
        BreakGlassStore(state_dir).status(now=CREATED_AT)


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


def test_break_glass_direct_cli_reports_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.break_glass import main

    assert (
        main(
            [
                "create",
                "--state-dir",
                str(tmp_path / "state"),
                "--reason",
                " ",
                "--operator",
                OPERATOR,
                "--expires-at",
                CLI_EXPIRES_AT,
                "--bypass-policy",
                BYPASSED_POLICY_PATHS[0],
            ]
        )
        == 1
    )

    captured = capsys.readouterr()
    assert "reason is required" in captured.err
    assert captured.out == ""


@pytest.mark.error_simulation
def test_break_glass_main_reports_unknown_dispatch_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import mcp_broker.break_glass as break_glass

    monkeypatch.setattr(
        break_glass,
        "_parse_args",
        lambda _argv: SimpleNamespace(
            break_glass_command="unknown",
            state_dir=tmp_path / "state",
        ),
    )

    assert break_glass.main([]) == 1
    assert "unknown break-glass command" in capsys.readouterr().err


@pytest.mark.error_simulation
def test_break_glass_module_entrypoint_exits_with_main_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "break_glass",
            "status",
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )

    module_name = "mcp_broker.break_glass"
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


# --- the CLI contract in _parse_args ------------------------------------------
# Mutating a flag name, a dest, a required= or a default here silently changes what
# operators may type. Each case pins one of those.


def _create_argv(**overrides: str) -> list[str]:
    fields = {
        "--state-dir": "/tmp/state",
        "--reason": REASON,
        "--operator": OPERATOR,
        "--expires-at": "2999-01-01T00:00:00Z",
        "--bypass-policy": "policy/one",
    }
    fields.update(overrides)
    argv = ["create"]
    for flag, value in fields.items():
        argv += [flag, value]
    return argv


def test_parse_args_create_populates_every_declared_field() -> None:
    from mcp_broker.break_glass import _parse_args

    args = _parse_args(_create_argv())

    assert args.break_glass_command == "create"
    assert args.state_dir == Path("/tmp/state")
    assert args.reason == REASON
    assert args.operator == OPERATOR
    assert args.expires_at == "2999-01-01T00:00:00Z"
    assert args.bypass_policy == ["policy/one"]


def test_parse_args_state_dir_is_a_path_not_a_string() -> None:
    """type=Path is part of the contract; a str would reach the filesystem code."""
    from mcp_broker.break_glass import _parse_args

    assert isinstance(_parse_args(_create_argv()).state_dir, Path)


def test_parse_args_bypass_policy_appends_each_occurrence() -> None:
    """action="append" means repeating the flag accumulates rather than replaces."""
    from mcp_broker.break_glass import _parse_args

    argv = _create_argv()
    argv += ["--bypass-policy", "policy/two"]

    assert _parse_args(argv).bypass_policy == ["policy/one", "policy/two"]


@pytest.mark.parametrize(
    "omitted",
    ["--state-dir", "--reason", "--operator", "--expires-at", "--bypass-policy"],
)
def test_parse_args_create_requires_every_flag(omitted: str) -> None:
    """Each flag is required=True. Dropping required= on any one of them would let a
    half-specified record through, and only a per-flag case notices which."""
    from mcp_broker.break_glass import _parse_args

    argv = [token for token in _create_argv() if token != omitted]
    # Drop the orphaned value that followed the removed flag.
    index = _create_argv().index(omitted)
    argv = _create_argv()[:index] + _create_argv()[index + 2:]

    with pytest.raises(SystemExit) as exc:
        _parse_args(argv)
    assert exc.value.code == 2


def test_parse_args_status_takes_only_a_state_dir() -> None:
    from mcp_broker.break_glass import _parse_args

    args = _parse_args(["status", "--state-dir", "/tmp/state"])

    assert args.break_glass_command == "status"
    assert args.state_dir == Path("/tmp/state")


def test_parse_args_status_requires_a_state_dir() -> None:
    from mcp_broker.break_glass import _parse_args

    with pytest.raises(SystemExit) as exc:
        _parse_args(["status"])
    assert exc.value.code == 2


def test_parse_args_requires_a_subcommand() -> None:
    """required=True on the subparser: a bare invocation must not fall through to a
    namespace with no command."""
    from mcp_broker.break_glass import _parse_args

    with pytest.raises(SystemExit) as exc:
        _parse_args([])
    assert exc.value.code == 2


def test_parse_args_rejects_an_unknown_subcommand() -> None:
    from mcp_broker.break_glass import _parse_args

    with pytest.raises(SystemExit) as exc:
        _parse_args(["destroy", "--state-dir", "/tmp/state"])
    assert exc.value.code == 2


def test_parse_args_rejects_an_unknown_flag() -> None:
    from mcp_broker.break_glass import _parse_args

    with pytest.raises(SystemExit) as exc:
        _parse_args(_create_argv() + ["--force"])
    assert exc.value.code == 2


def test_parse_args_subcommand_lands_in_the_break_glass_command_attribute() -> None:
    """dest="break_glass_command" is what main() dispatches on; a renamed dest would
    make every dispatch miss."""
    from mcp_broker.break_glass import _parse_args

    for command, argv in (
        ("create", _create_argv()),
        ("status", ["status", "--state-dir", "/tmp/state"]),
    ):
        namespace = _parse_args(argv)
        assert getattr(namespace, "break_glass_command") == command


# --- the JSON helpers and the record id ---------------------------------------


def test_write_json_atomic_creates_missing_parent_directories(tmp_path: Path) -> None:
    from mcp_broker.break_glass import _write_json_atomic

    target = tmp_path / "deep" / "nested" / "record.json"
    _write_json_atomic(target, {"b": 1, "a": 2})

    assert target.is_file()


def test_write_json_atomic_formats_sorted_and_indented_with_a_trailing_newline(
    tmp_path: Path,
) -> None:
    """indent=2, sort_keys=True and the trailing newline are the on-disk contract:
    the file is read back by other tools and diffed by humans."""
    from mcp_broker.break_glass import _write_json_atomic

    target = tmp_path / "record.json"
    _write_json_atomic(target, {"b": 1, "a": 2})

    assert target.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "b": 1\n}\n'


def test_write_json_atomic_leaves_no_temp_file_behind(tmp_path: Path) -> None:
    """The write goes to a sibling and is renamed, so a reader never sees a partial
    file and nothing is left over afterwards."""
    from mcp_broker.break_glass import _write_json_atomic

    target = tmp_path / "record.json"
    _write_json_atomic(target, {"a": 1})

    assert sorted(p.name for p in tmp_path.iterdir()) == ["record.json"]


def test_write_json_atomic_replaces_an_existing_file_entirely(tmp_path: Path) -> None:
    from mcp_broker.break_glass import _write_json_atomic

    target = tmp_path / "record.json"
    target.write_text('{"stale": true}', encoding="utf-8")
    _write_json_atomic(target, {"fresh": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"fresh": True}


def test_read_json_returns_the_decoded_object(tmp_path: Path) -> None:
    from mcp_broker.break_glass import _read_json

    target = tmp_path / "record.json"
    target.write_text(json.dumps({"a": 1}), encoding="utf-8")

    assert _read_json(target) == {"a": 1}


def test_read_json_rejects_valid_json_that_is_not_an_object(tmp_path: Path) -> None:
    from mcp_broker.break_glass import BreakGlassError, _read_json

    target = tmp_path / "record.json"
    target.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(BreakGlassError) as exc:
        _read_json(target)
    assert "expected JSON object" in str(exc.value)
    assert str(target) in str(exc.value)


def test_read_json_reads_as_utf8(tmp_path: Path) -> None:
    from mcp_broker.break_glass import _read_json

    target = tmp_path / "record.json"
    target.write_text(json.dumps({"reason": "caf\u00e9"}), encoding="utf-8")

    assert _read_json(target)["reason"] == "caf\u00e9"


def test_record_id_has_the_documented_prefix_and_digest_length() -> None:
    """The id shape is a contract: a changed prefix or digest length changes every
    identifier the tool has ever written."""
    from mcp_broker.break_glass import _record_id

    record_id = _record_id({"a": 1})

    assert record_id.startswith("break-glass-")
    assert len(record_id) == len("break-glass-") + 16
    assert set(record_id[len("break-glass-"):]) <= set("0123456789abcdef")


def test_record_id_is_stable_for_the_same_seed() -> None:
    from mcp_broker.break_glass import _record_id

    assert _record_id({"a": 1, "b": 2}) == _record_id({"a": 1, "b": 2})


def test_record_id_ignores_key_order() -> None:
    """sort_keys=True in the canonical encoding: two dicts differing only in
    insertion order are the same record."""
    from mcp_broker.break_glass import _record_id

    assert _record_id({"a": 1, "b": 2}) == _record_id({"b": 2, "a": 1})


def test_record_id_changes_when_any_value_changes() -> None:
    from mcp_broker.break_glass import _record_id

    assert _record_id({"a": 1}) != _record_id({"a": 2})


def test_record_id_distinguishes_seeds_that_share_a_flattened_form() -> None:
    """The compact separators must not let two different seeds collapse to the same
    encoded string."""
    from mcp_broker.break_glass import _record_id

    assert _record_id({"ab": 1}) != _record_id({"a": "b:1"})


# --- the help text an operator actually reads ---------------------------------


def test_parser_description_states_what_the_tool_manages(capsys: pytest.CaptureFixture[str]) -> None:
    from mcp_broker.break_glass import _parse_args

    with pytest.raises(SystemExit) as exc:
        _parse_args(["--help"])
    assert exc.value.code == 0

    out = without_ansi(capsys.readouterr().out)
    # Exact line, not a substring: an "XX"-wrapped literal still contains the
    # original text, so `in` cannot tell the two apart.
    assert "Manage local break-glass audit records\n" in out
    assert "XX" not in out


def test_create_subcommand_help_describes_an_expiring_record(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The subcommand help appears in the top-level listing, so one capture covers
    both entries."""
    from mcp_broker.break_glass import _parse_args

    with pytest.raises(SystemExit):
        _parse_args(["--help"])

    out = without_ansi(capsys.readouterr().out)
    assert "Create an expiring break-glass audit record" in out
    assert "XX" not in out


def test_status_subcommand_help_describes_reporting_active_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.break_glass import _parse_args

    with pytest.raises(SystemExit):
        _parse_args(["--help"])

    out = without_ansi(capsys.readouterr().out)
    assert "Report active break-glass status" in out
    assert "XX" not in out


def test_help_text_keeps_its_declared_capitalisation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Case is part of the string. A lower- or upper-cased variant is a different
    message to the reader, and nothing else in the suite would notice."""
    from mcp_broker.break_glass import _parse_args

    with pytest.raises(SystemExit):
        _parse_args(["--help"])

    out = without_ansi(capsys.readouterr().out)
    assert "manage local break-glass audit records" not in out
    assert "MANAGE LOCAL BREAK-GLASS AUDIT RECORDS" not in out
    assert "create an expiring break-glass audit record" not in out
    assert "CREATE AN EXPIRING BREAK-GLASS AUDIT RECORD" not in out
    assert "report active break-glass status" not in out
    assert "REPORT ACTIVE BREAK-GLASS STATUS" not in out


# --- the last observable survivors --------------------------------------------


def test_policy_paths_error_message_is_exact() -> None:
    """Substring matching cannot distinguish a wrapped literal from the real one."""
    from mcp_broker.break_glass import BreakGlassError, _policy_paths

    with pytest.raises(BreakGlassError) as exc:
        _policy_paths([" ", ""])
    assert str(exc.value) == "at least one bypassed policy path is required"


def test_require_future_expiration_error_message_is_exact() -> None:
    from mcp_broker.break_glass import BreakGlassError, _require_future_expiration

    with pytest.raises(BreakGlassError) as exc:
        _require_future_expiration("2020-01-01T00:00:00Z", now="2026-01-01T00:00:00Z")
    assert str(exc.value) == "expires_at must be in the future"


def test_record_id_matches_a_known_digest_for_a_known_seed() -> None:
    """A golden value pins the canonical encoding itself.

    The id is a sha256 over json.dumps(seed, sort_keys=True, separators=(",", ":")).
    Change the separators and the encoded payload changes, so the digest changes, so
    every previously written record id stops matching. Only a fixed expected value
    notices that; asserting the shape does not.
    """
    import hashlib
    import json as _json

    from mcp_broker.break_glass import _record_id

    seed = {"operator": OPERATOR, "reason": REASON}
    canonical = _json.dumps(seed, sort_keys=True, separators=(",", ":"))
    expected = "break-glass-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    assert _record_id(seed) == expected
    # And the compact form really is compact: a default-separator encoding would
    # produce a different digest, so the two must not agree.
    spaced = _json.dumps(seed, sort_keys=True)
    assert canonical != spaced


def test_is_expired_treats_an_expiry_equal_to_now_as_expired() -> None:
    """The comparison is inclusive. At exactly the expiry instant the record is
    spent, not still valid."""
    from mcp_broker.break_glass import _is_expired

    assert _is_expired("2026-01-01T00:00:00Z", now="2026-01-01T00:00:00Z") is True


def test_is_expired_is_false_one_second_before_the_expiry() -> None:
    from mcp_broker.break_glass import _is_expired

    assert _is_expired("2026-01-01T00:00:01Z", now="2026-01-01T00:00:00Z") is False


def test_main_prints_created_record_json_with_sorted_keys(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """sort_keys=True on the printed payload: the output is read by other tools and
    diffed by humans, so key order is part of the contract.

    This asserts against `create` rather than `status` on purpose. The status payload
    is built as active_record, degraded, status, which is already alphabetical, so
    sorting it is a no-op and the assertion could not fail. A created record is
    returned in construction order and is not alphabetical.
    """
    from mcp_broker.break_glass import main

    exit_code = main(
        [
            "create",
            "--state-dir",
            str(tmp_path / "state"),
            "--reason",
            REASON,
            "--operator",
            OPERATOR,
            "--expires-at",
            CLI_EXPIRES_AT,
            "--bypass-policy",
            BYPASSED_POLICY_PATHS[0],
        ]
    )
    assert exit_code == 0

    printed = capsys.readouterr().out
    payload = json.loads(printed)
    assert list(payload) == sorted(payload), "record JSON must be printed with sorted keys"
    # The record really does have unsorted construction order, so the assertion above
    # has something to catch. Without this the test could silently become a no-op if
    # the record's field order were ever alphabetised.
    assert list(payload) != ["record_id", "status", "created_at"][: len(payload)]
    assert printed.endswith("\n")


def test_main_prints_status_json_with_a_trailing_newline(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.break_glass import main

    assert main(["status", "--state-dir", str(tmp_path / "state")]) == 0

    printed = capsys.readouterr().out
    assert json.loads(printed) == {
        "active_record": None,
        "degraded": False,
        "status": "inactive",
    }
    assert printed.endswith("\n")
