from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys
from unittest.mock import Mock, mock_open

import pytest

from mcp_broker.cli import main as cli_main


pytestmark = [pytest.mark.unit]


def test_rollout_controller_writes_auditable_actions_without_runtime_mutation(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_rollout_controller import control_rollout

    state_dir = tmp_path / "state"

    result = control_rollout(
        simulation=_ready_simulation(),
        state_dir=state_dir,
        operator="release-operator",
        bundle=_bundle_metadata(),
        created_at="2026-07-04T05:00:00Z",
    )

    assert result["schema_version"] == 1
    assert result["action_count"] == 3
    assert result["changed_runtime_state"] is False
    assert result["audit_log_path"] == str(
        state_dir / "governance-rollout" / "action-log.jsonl"
    )
    assert result["action_paths"] == [
        str(state_dir / "governance-rollout" / "actions" / "0001-broker-a-canary.json"),
        str(state_dir / "governance-rollout" / "actions" / "0002-broker-b-staged.json"),
        str(state_dir / "governance-rollout" / "actions" / "0003-broker-c-broad.json"),
    ]

    records = [
        json.loads(Path(action_path).read_text(encoding="utf-8"))
        for action_path in result["action_paths"]
    ]
    assert [record["action"] for record in records] == ["canary", "staged", "broad"]
    assert [record["broker_id"] for record in records] == [
        "broker-a",
        "broker-b",
        "broker-c",
    ]
    assert [record["stage"] for record in records] == ["canary", "staged", "broad"]
    assert [record["requires_approval"] for record in records] == [False, False, False]
    assert [record["changed_runtime_state"] for record in records] == [
        False,
        False,
        False,
    ]
    assert {record["operator"] for record in records} == {"release-operator"}
    assert {record["created_at"] for record in records} == {"2026-07-04T05:00:00Z"}
    assert {record["source_state"] for record in records} == {"ready"}
    assert {record["mode"] for record in records} == {"local_simulation_only"}
    assert {record["bundle"]["version"] for record in records} == {"2026.07.04"}
    assert {record["bundle"]["digest"]["value"] for record in records} == {"abc123"}

    audit_lines = (state_dir / "governance-rollout" / "action-log.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    assert [json.loads(line)["action_id"] for line in audit_lines] == [
        "0001-broker-a-canary",
        "0002-broker-b-staged",
        "0003-broker-c-broad",
    ]


def test_rollout_controller_records_hold_when_approval_is_missing(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_rollout_controller import control_rollout

    result = control_rollout(
        simulation={
            "mode": "local_simulation_only",
            "state": "approval_required",
            "decisions": [],
            "reasons": ["policy approval_required is true and approval was not granted"],
        },
        state_dir=tmp_path / "state",
        operator="release-operator",
        bundle=_bundle_metadata(),
        created_at="2026-07-04T05:10:00Z",
    )

    record = json.loads(Path(result["action_paths"][0]).read_text(encoding="utf-8"))
    assert result["action_count"] == 1
    assert record["action"] == "hold"
    assert record["broker_id"] == "fleet"
    assert record["requires_approval"] is True
    assert record["reasons"] == [
        "policy approval_required is true and approval was not granted"
    ]
    assert record["changed_runtime_state"] is False


def test_rollout_controller_records_hold_for_compatibility_rejection(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_rollout_controller import control_rollout

    result = control_rollout(
        simulation={
            "mode": "local_simulation_only",
            "state": "compatibility_rejection",
            "decisions": [],
            "reasons": ["broker-a is not targeted"],
        },
        state_dir=tmp_path / "state",
        operator="release-operator",
        bundle=_bundle_metadata(),
        created_at="2026-07-04T05:11:00Z",
    )

    record = json.loads(Path(result["action_paths"][0]).read_text(encoding="utf-8"))
    assert record["action"] == "hold"
    assert record["requires_approval"] is False
    assert record["reasons"] == ["broker-a is not targeted"]


def test_rollout_controller_records_rollback_actions_for_unhealthy_brokers(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_rollout_controller import control_rollout

    result = control_rollout(
        simulation={
            "mode": "local_simulation_only",
            "state": "rollback",
            "decisions": [
                {"broker_id": "broker-a", "stage": "canary", "state": "rollback"}
            ],
            "reasons": ["broker-a health status degraded triggers rollback"],
        },
        state_dir=tmp_path / "state",
        operator="release-operator",
        bundle=_bundle_metadata(),
        created_at="2026-07-04T05:20:00Z",
    )

    record = json.loads(Path(result["action_paths"][0]).read_text(encoding="utf-8"))
    assert result["action_count"] == 1
    assert record["action"] == "rollback"
    assert record["broker_id"] == "broker-a"
    assert record["stage"] == "canary"
    assert record["requires_approval"] is False
    assert record["reasons"] == ["broker-a health status degraded triggers rollback"]


def test_rollout_controller_rejects_non_local_simulation(tmp_path: Path) -> None:
    from mcp_broker.governance_rollout_controller import (
        GovernanceRolloutControllerError,
        control_rollout,
    )

    with pytest.raises(GovernanceRolloutControllerError, match="local simulation"):
        control_rollout(
            simulation={
                "mode": "remote_control_plane",
                "state": "ready",
                "decisions": [],
                "reasons": [],
            },
            state_dir=tmp_path / "state",
            operator="release-operator",
            bundle=_bundle_metadata(),
            created_at="2026-07-04T05:30:00Z",
        )


@pytest.mark.parametrize(
    ("simulation", "message"),
    [
        (
            {"mode": "local_simulation_only", "decisions": [], "reasons": []},
            "simulation state is required",
        ),
        (
            {
                "mode": "local_simulation_only",
                "state": "ready",
                "decisions": {},
                "reasons": [],
            },
            "simulation decisions must be a list",
        ),
        (
            {
                "mode": "local_simulation_only",
                "state": "ready",
                "decisions": [],
                "reasons": {},
            },
            "simulation reasons must be a list",
        ),
        (
            {
                "mode": "local_simulation_only",
                "state": "ready",
                "decisions": [],
                "reasons": [],
            },
            "simulation decisions are required",
        ),
        (
            {
                "mode": "local_simulation_only",
                "state": "ready",
                "decisions": [{"broker_id": "broker-a", "stage": "canary", "state": "paused"}],
                "reasons": [],
            },
            "unsupported decision state",
        ),
        (
            {
                "mode": "local_simulation_only",
                "state": "ready",
                "decisions": [{"stage": "canary", "state": "canary"}],
                "reasons": [],
            },
            "broker_id is required",
        ),
    ],
)
def test_rollout_controller_rejects_malformed_simulation(
    tmp_path: Path,
    simulation: dict[str, object],
    message: str,
) -> None:
    from mcp_broker.governance_rollout_controller import (
        GovernanceRolloutControllerError,
        control_rollout,
    )

    with pytest.raises(GovernanceRolloutControllerError, match=message):
        control_rollout(
            simulation=simulation,
            state_dir=tmp_path / "state",
            operator="release-operator",
            bundle=_bundle_metadata(),
            created_at="2026-07-04T05:30:00Z",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("bundle_id", "", "bundle_id is required"),
        ("version", "", "bundle_version is required"),
        ("channel", "", "bundle_channel is required"),
        ("digest.algorithm", "", "digest algorithm is required"),
        ("digest.value", "", "digest value is required"),
    ],
)
def test_rollout_controller_rejects_bad_bundle_metadata(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    from mcp_broker.governance_rollout_controller import (
        GovernanceRolloutControllerError,
        control_rollout,
    )

    bundle = _bundle_metadata()
    if field.startswith("digest."):
        digest = bundle["digest"]
        assert isinstance(digest, dict)
        digest[field.split(".", maxsplit=1)[1]] = value
    else:
        bundle[field] = value

    with pytest.raises(GovernanceRolloutControllerError, match=message):
        control_rollout(
            simulation=_ready_simulation(),
            state_dir=tmp_path / "state",
            operator="release-operator",
            bundle=bundle,
            created_at="2026-07-04T05:30:00Z",
        )


def test_rollout_controller_rejects_empty_operator(tmp_path: Path) -> None:
    from mcp_broker.governance_rollout_controller import (
        GovernanceRolloutControllerError,
        control_rollout,
    )

    with pytest.raises(GovernanceRolloutControllerError, match="operator is required"):
        control_rollout(
            simulation=_ready_simulation(),
            state_dir=tmp_path / "state",
            operator=" ",
            bundle=_bundle_metadata(),
            created_at="2026-07-04T05:30:00Z",
        )


def test_rollout_controller_rejects_empty_sanitized_action_id_component() -> None:
    from mcp_broker.governance_rollout_controller import (
        GovernanceRolloutControllerError,
        _safe_id_part,
    )

    with pytest.raises(GovernanceRolloutControllerError) as exc_info:
        _safe_id_part("!!!")
    assert str(exc_info.value) == "empty action id component"


def test_rollout_controller_safe_id_preserves_valid_x_characters() -> None:
    from mcp_broker.governance_rollout_controller import _safe_id_part

    assert _safe_id_part("XvalueX") == "XvalueX"


def test_rollout_controller_rejects_duplicate_action_records(tmp_path: Path) -> None:
    from mcp_broker.governance_rollout_controller import (
        GovernanceRolloutControllerError,
        control_rollout,
    )

    kwargs = {
        "simulation": _ready_simulation(),
        "state_dir": tmp_path / "state",
        "operator": "release-operator",
        "bundle": _bundle_metadata(),
        "created_at": "2026-07-04T05:30:00Z",
    }
    control_rollout(**kwargs)

    with pytest.raises(GovernanceRolloutControllerError, match="rollout action already exists"):
        control_rollout(**kwargs)


def test_rollout_controller_cli_writes_records_and_prints_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    simulation_path = tmp_path / "simulation.json"
    simulation_path.write_text(json.dumps(_ready_simulation()), encoding="utf-8")

    assert (
        cli_main(
            [
                "governance",
                "rollout-control",
                "--simulation",
                str(simulation_path),
                "--state-dir",
                str(tmp_path / "state"),
                "--operator",
                "release-operator",
                "--bundle-id",
                "governance-bundle",
                "--bundle-version",
                "2026.07.04",
                "--bundle-channel",
                "stable",
                "--bundle-digest",
                "sha256:abc123",
                "--created-at",
                "2026-07-04T05:40:00Z",
            ]
        )
        == 0
    )

    stdout = capsys.readouterr().out
    assert "governance rollout actions recorded: 3" in stdout
    assert "record=" in stdout
    assert (tmp_path / "state" / "governance-rollout" / "action-log.jsonl").is_file()


def test_rollout_controller_direct_cli_reports_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.governance_rollout_controller import main

    simulation_path = tmp_path / "simulation.json"
    simulation_path.write_text("[]", encoding="utf-8")

    assert (
        main(
            [
                "--simulation",
                str(simulation_path),
                "--state-dir",
                str(tmp_path / "state"),
                "--operator",
                "release-operator",
                "--bundle-id",
                "governance-bundle",
                "--bundle-version",
                "2026.07.04",
                "--bundle-channel",
                "stable",
                "--bundle-digest",
                "sha256:abc123",
            ]
        )
        == 1
    )
    assert "expected JSON object" in capsys.readouterr().out


def test_rollout_controller_cli_rejects_bad_digest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.governance_rollout_controller import main

    simulation_path = tmp_path / "simulation.json"
    simulation_path.write_text(json.dumps(_ready_simulation()), encoding="utf-8")

    assert (
        main(
            [
                "--simulation",
                str(simulation_path),
                "--state-dir",
                str(tmp_path / "state"),
                "--operator",
                "release-operator",
                "--bundle-id",
                "governance-bundle",
                "--bundle-version",
                "2026.07.04",
                "--bundle-channel",
                "stable",
                "--bundle-digest",
                "sha256",
            ]
        )
        == 1
    )
    assert "bundle digest must be algorithm:value" in capsys.readouterr().out


def test_rollout_controller_digest_parser_preserves_value_delimiters_and_trims() -> None:
    from mcp_broker.governance_rollout_controller import _parse_digest

    assert _parse_digest(" sha256 : abc:def ") == {
        "algorithm": "sha256",
        "value": "abc:def",
    }


@pytest.mark.parametrize(
    ("digest", "message"),
    [
        ("sha256", "bundle digest must be algorithm:value"),
        (":abc123", "digest algorithm is required"),
        ("sha256:", "digest value is required"),
    ],
)
def test_rollout_controller_digest_parser_rejects_incomplete_values(
    digest: str,
    message: str,
) -> None:
    from mcp_broker.governance_rollout_controller import (
        GovernanceRolloutControllerError,
        _parse_digest,
    )

    with pytest.raises(GovernanceRolloutControllerError) as exc_info:
        _parse_digest(digest)
    assert str(exc_info.value) == message


def test_rollout_controller_json_loader_opens_expanded_path_as_utf8() -> None:
    from mcp_broker.governance_rollout_controller import _load_json_mapping

    path = Mock()
    expanded_path = Mock()
    expanded_path.open = mock_open(read_data='{"state": "ready"}')
    path.expanduser.return_value = expanded_path

    assert _load_json_mapping(path) == {"state": "ready"}
    path.expanduser.assert_called_once_with()
    expanded_path.open.assert_called_once_with("r", encoding="utf-8")


def test_rollout_controller_parser_has_exact_public_contract() -> None:
    from mcp_broker.governance_rollout_controller import _parser

    parser = _parser()
    assert parser.description == "Record local rollout-control actions"
    actions = {action.dest: action for action in parser._actions}
    assert set(actions) == {
        "help",
        "simulation",
        "state_dir",
        "operator",
        "bundle_id",
        "bundle_version",
        "bundle_channel",
        "bundle_digest",
        "created_at",
    }
    for name in {
        "simulation",
        "state_dir",
        "operator",
        "bundle_id",
        "bundle_version",
        "bundle_channel",
        "bundle_digest",
    }:
        assert actions[name].required is True
    assert actions["created_at"].required is False
    assert actions["simulation"].type is Path
    assert actions["state_dir"].type is Path


@pytest.mark.error_simulation
def test_rollout_controller_module_entrypoint_exits_with_main_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    simulation_path = tmp_path / "simulation.json"
    simulation_path.write_text(json.dumps(_ready_simulation()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "governance_rollout_controller",
            "--simulation",
            str(simulation_path),
            "--state-dir",
            str(tmp_path / "state"),
            "--operator",
            "release-operator",
            "--bundle-id",
            "governance-bundle",
            "--bundle-version",
            "2026.07.04",
            "--bundle-channel",
            "stable",
            "--bundle-digest",
            "sha256:abc123",
        ],
    )

    module_name = "mcp_broker.governance_rollout_controller"
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


def _ready_simulation() -> dict[str, object]:
    return {
        "mode": "local_simulation_only",
        "state": "ready",
        "decisions": [
            {"broker_id": "broker-a", "stage": "canary", "state": "canary"},
            {"broker_id": "broker-b", "stage": "staged", "state": "staged_rollout"},
            {"broker_id": "broker-c", "stage": "broad", "state": "broad_rollout"},
        ],
        "reasons": [],
    }


def _bundle_metadata() -> dict[str, object]:
    return {
        "bundle_id": "governance-bundle",
        "version": "2026.07.04",
        "channel": "stable",
        "digest": {
            "algorithm": "sha256",
            "value": "abc123",
        },
    }


# --- the action records a rollout writes ---------------------------------------


def _records(simulation: dict[str, object] | None = None) -> list[dict[str, object]]:
    from mcp_broker.governance_rollout_controller import _records_from_simulation

    return _records_from_simulation(
        simulation=simulation or _ready_simulation(),
        operator="release-operator",
        bundle=_bundle_metadata(),
        created_at="2026-07-04T05:00:00Z",
    )


def test_record_carries_every_field_including_the_no_mutation_claim() -> None:
    """changed_runtime_state is the controller's claim that planning touched
    nothing. requires_approval is the claim that it may proceed. Both are part of the
    audit record and neither was asserted."""
    first = _records()[0]

    assert first == {
        "schema_version": 1,
        "action_id": "0001-broker-a-canary",
        "created_at": "2026-07-04T05:00:00Z",
        "operator": "release-operator",
        "mode": "local_simulation_only",
        "source_state": "ready",
        "bundle": _bundle_metadata(),
        "broker_id": "broker-a",
        "stage": "canary",
        "action": "canary",
        "requires_approval": False,
        "changed_runtime_state": False,
        "reasons": [],
        "decision": {
            "broker_id": "broker-a",
            "stage": "canary",
            "state": "canary",
        },
    }


def test_action_ids_are_zero_padded_and_numbered_from_one() -> None:
    """The index is 4-digit zero padded and starts at 1, not 0. Operators quote
    these ids, and sorting them lexically has to match their order."""
    ids = [record["action_id"] for record in _records()]

    assert ids == [
        "0001-broker-a-canary",
        "0002-broker-b-staged",
        "0003-broker-c-broad",
    ]
    assert ids == sorted(ids)


def test_every_decision_state_maps_to_its_own_action() -> None:
    """A mutated mapping would file a rollback as a canary."""
    from mcp_broker.governance_rollout_controller import _action_for_decision_state

    assert _action_for_decision_state("canary") == "canary"
    assert _action_for_decision_state("staged_rollout") == "staged"
    assert _action_for_decision_state("broad_rollout") == "broad"
    assert _action_for_decision_state("rollback") == "rollback"


def test_an_unsupported_decision_state_is_rejected_by_name() -> None:
    from mcp_broker.governance_rollout_controller import (
        GovernanceRolloutControllerError,
        _action_for_decision_state,
    )

    with pytest.raises(GovernanceRolloutControllerError) as exc:
        _action_for_decision_state("sideways")
    assert str(exc.value) == "unsupported decision state: sideways"


@pytest.mark.parametrize(
    ("state", "requires_approval"),
    [("approval_required", True), ("compatibility_rejection", False)],
)
def test_a_holding_state_produces_one_fleet_wide_hold(
    state: str, requires_approval: bool
) -> None:
    """Both holding states collapse to a single fleet action, and only
    approval_required asks for approval."""
    records = _records({"state": state, "reasons": ["needs sign-off"]})

    assert len(records) == 1
    assert records[0]["action_id"] == "0001-fleet-hold"
    assert records[0]["broker_id"] == "fleet"
    assert records[0]["stage"] == "fleet"
    assert records[0]["action"] == "hold"
    assert records[0]["source_state"] == state
    assert records[0]["requires_approval"] is requires_approval
    assert records[0]["reasons"] == ["needs sign-off"]
    assert records[0]["decision"] == {}


def test_a_proceeding_state_never_requires_approval() -> None:
    assert all(record["requires_approval"] is False for record in _records())


def test_reasons_are_carried_onto_every_record() -> None:
    simulation = _ready_simulation()
    simulation["reasons"] = ["one", "two"]

    assert all(record["reasons"] == ["one", "two"] for record in _records(simulation))


def test_a_proceeding_simulation_without_decisions_is_rejected() -> None:
    from mcp_broker.governance_rollout_controller import GovernanceRolloutControllerError

    with pytest.raises(GovernanceRolloutControllerError) as exc:
        _records({"state": "ready", "decisions": [], "reasons": []})
    assert str(exc.value) == "simulation decisions are required"


# --- the bundle metadata --------------------------------------------------------


def test_bundle_metadata_carries_the_five_declared_fields() -> None:
    from mcp_broker.governance_rollout_controller import _bundle_metadata as extract

    assert extract(_bundle_metadata()) == {
        "bundle_id": "governance-bundle",
        "version": "2026.07.04",
        "channel": "stable",
        "digest": {"algorithm": "sha256", "value": "abc123"},
    }


@pytest.mark.parametrize(
    ("missing", "label"),
    [
        ("bundle_id", "bundle_id"),
        ("version", "bundle_version"),
        ("channel", "bundle_channel"),
    ],
)
def test_bundle_metadata_names_each_missing_top_level_field(
    missing: str, label: str
) -> None:
    """The label is what an operator reads, and it is not always the key name:
    version reports as bundle_version."""
    from mcp_broker.governance_rollout_controller import (
        GovernanceRolloutControllerError,
        _bundle_metadata as extract,
    )

    bundle = _bundle_metadata()
    del bundle[missing]

    with pytest.raises(GovernanceRolloutControllerError) as exc:
        extract(bundle)
    assert label in str(exc.value)


@pytest.mark.parametrize(
    ("missing", "label"),
    [("algorithm", "digest algorithm"), ("value", "digest value")],
)
def test_bundle_metadata_names_each_missing_digest_field(
    missing: str, label: str
) -> None:
    from mcp_broker.governance_rollout_controller import (
        GovernanceRolloutControllerError,
        _bundle_metadata as extract,
    )

    bundle = _bundle_metadata()
    del bundle["digest"][missing]

    with pytest.raises(GovernanceRolloutControllerError) as exc:
        extract(bundle)
    assert label in str(exc.value)


# --- the on-disk formats --------------------------------------------------------


def test_write_json_new_formats_sorted_and_indented_with_a_trailing_newline(
    tmp_path: Path,
) -> None:
    from mcp_broker.governance_rollout_controller import _write_json_new

    target = tmp_path / "record.json"
    _write_json_new(target, {"b": 1, "a": 2})

    assert target.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "b": 1\n}\n'


def test_write_json_new_refuses_to_overwrite_an_existing_record(tmp_path: Path) -> None:
    from mcp_broker.governance_rollout_controller import _write_json_new

    target = tmp_path / "record.json"
    _write_json_new(target, {"a": 1})

    with pytest.raises(Exception):
        _write_json_new(target, {"a": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}


def test_write_json_new_writes_through_a_temp_sibling_and_leaves_none_behind(
    tmp_path: Path,
) -> None:
    """The write lands on a .tmp sibling and is renamed, so a reader never sees a
    partial file. This module's writer does not create parents; its caller does."""
    from mcp_broker.governance_rollout_controller import _write_json_new

    target = tmp_path / "record.json"
    _write_json_new(target, {"a": 1})

    assert sorted(p.name for p in tmp_path.iterdir()) == ["record.json"]


def test_append_jsonl_writes_one_sorted_line_per_record(tmp_path: Path) -> None:
    """It takes a sequence of records and writes one line each, keys sorted. The
    mapping is deliberately not already alphabetical: an entry that is cannot show
    whether sort_keys does anything."""
    from mcp_broker.governance_rollout_controller import _append_jsonl

    target = tmp_path / "audit.jsonl"
    _append_jsonl(target, [{"zebra": 1, "apple": 2}, {"b": 3}])

    assert target.read_text(encoding="utf-8") == (
        '{"apple": 2, "zebra": 1}\n{"b": 3}\n'
    )


def test_append_jsonl_appends_rather_than_replacing(tmp_path: Path) -> None:
    """Append mode is the point of an audit file: a later batch must not erase an
    earlier one."""
    from mcp_broker.governance_rollout_controller import _append_jsonl

    target = tmp_path / "audit.jsonl"
    _append_jsonl(target, [{"a": 1}])
    _append_jsonl(target, [{"b": 2}])

    assert target.read_text(encoding="utf-8") == '{"a": 1}\n{"b": 2}\n'


def test_append_jsonl_writes_nothing_for_an_empty_sequence(tmp_path: Path) -> None:
    from mcp_broker.governance_rollout_controller import _append_jsonl

    target = tmp_path / "audit.jsonl"
    _append_jsonl(target, [])

    assert target.read_text(encoding="utf-8") == ""


# --- the generated timestamp, the audit entry, and the validation messages ------


def test_control_rollout_generates_a_utc_second_resolution_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without created_at the controller stamps its own time: UTC, whole seconds.
    Microseconds would make two records from one batch sort unstably, and a local
    clock would file the batch under the operator's zone."""
    import time

    from mcp_broker.governance_rollout_controller import control_rollout

    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    try:
        result = control_rollout(
            simulation=_ready_simulation(),
            state_dir=tmp_path / "state",
            operator="release-operator",
            bundle=_bundle_metadata(),
        )
    finally:
        monkeypatch.delenv("TZ", raising=False)
        time.tzset()

    action_path = Path(result["action_paths"][0])
    created = json.loads(action_path.read_text(encoding="utf-8"))["created_at"]

    assert created.endswith("+00:00"), created
    assert "." not in created, "microseconds must be truncated"


def test_control_rollout_writes_the_rollout_control_audit_action(tmp_path: Path) -> None:
    from mcp_broker.governance_rollout_controller import control_rollout

    state_dir = tmp_path / "state"
    result = control_rollout(
        simulation=_ready_simulation(),
        state_dir=state_dir,
        operator="release-operator",
        bundle=_bundle_metadata(),
        created_at="2026-07-04T05:00:00Z",
    )

    audit_log_path = state_dir / "governance-rollout" / "action-log.jsonl"

    # The summary names what the controller did and where it put things.
    assert result["action"] == "rollout-control"
    assert result["action_count"] == 3
    assert result["audit_log_path"] == str(audit_log_path)
    assert result["changed_runtime_state"] is False
    assert result["schema_version"] == 1
    assert len(result["action_paths"]) == 3

    # And one audit line landed per action.
    assert len(audit_log_path.read_text(encoding="utf-8").splitlines()) == 3


@pytest.mark.parametrize(
    ("simulation", "message"),
    [
        ({"mode": "remote", "state": "ready"},
         "rollout controller accepts only local simulation results"),
        ({"mode": "local_simulation_only"},
         "simulation state is required"),
        ({"mode": "local_simulation_only", "state": "ready", "decisions": {}},
         "simulation decisions must be a list"),
        ({"mode": "local_simulation_only", "state": "ready", "reasons": {}},
         "simulation reasons must be a list"),
    ],
)
def test_validate_simulation_messages_are_exact(
    simulation: dict[str, object], message: str
) -> None:
    from mcp_broker.governance_rollout_controller import (
        GovernanceRolloutControllerError,
        _validate_simulation,
    )

    with pytest.raises(GovernanceRolloutControllerError) as exc:
        _validate_simulation(simulation)
    assert str(exc.value) == message


# --- absent keys, not empty ones ------------------------------------------------


def test_a_simulation_without_a_reasons_key_yields_empty_reasons() -> None:
    """The default is only observable when the key is absent; an empty list present
    exercises nothing."""
    records = _records({"state": "ready", "decisions": _ready_simulation()["decisions"]})

    assert all(record["reasons"] == [] for record in records)


def test_a_proceeding_simulation_without_a_decisions_key_is_rejected() -> None:
    from mcp_broker.governance_rollout_controller import GovernanceRolloutControllerError

    with pytest.raises(GovernanceRolloutControllerError) as exc:
        _records({"state": "ready"})
    assert str(exc.value) == "simulation decisions are required"


def test_a_hold_record_carries_the_mode_operator_and_timestamp() -> None:
    """The hold path builds its record with its own arguments, and those three were
    not asserted anywhere."""
    record = _records({"state": "approval_required", "reasons": []})[0]

    assert record["mode"] == "local_simulation_only"
    assert record["operator"] == "release-operator"
    assert record["created_at"] == "2026-07-04T05:00:00Z"
    assert record["bundle"] == _bundle_metadata()


# --- the error labels an operator reads -----------------------------------------


def test_a_decision_missing_its_stage_is_named_by_label() -> None:
    from mcp_broker.governance_rollout_controller import GovernanceRolloutControllerError

    with pytest.raises(GovernanceRolloutControllerError) as exc:
        _records(
            {
                "state": "ready",
                "decisions": [{"broker_id": "broker-a", "state": "canary"}],
                "reasons": [],
            }
        )
    assert str(exc.value) == "stage is required"


def test_a_decision_missing_its_state_is_named_by_label() -> None:
    """The label is "decision state", not "state": the two would send an operator to
    different fields."""
    from mcp_broker.governance_rollout_controller import GovernanceRolloutControllerError

    with pytest.raises(GovernanceRolloutControllerError) as exc:
        _records(
            {
                "state": "ready",
                "decisions": [{"broker_id": "broker-a", "stage": "canary"}],
                "reasons": [],
            }
        )
    assert str(exc.value) == "decision state is required"


def test_a_decision_missing_its_broker_id_is_named_by_label() -> None:
    from mcp_broker.governance_rollout_controller import GovernanceRolloutControllerError

    with pytest.raises(GovernanceRolloutControllerError) as exc:
        _records(
            {
                "state": "ready",
                "decisions": [{"stage": "canary", "state": "canary"}],
                "reasons": [],
            }
        )
    assert str(exc.value) == "broker_id is required"


def test_main_passes_the_operators_created_at_through_to_the_record(
    tmp_path: Path,
) -> None:
    """Without this the controller stamps its own time, which is still a valid
    timestamp, so only the operator's own value shows the argument is wired."""
    from mcp_broker.governance_rollout_controller import main

    simulation_path = tmp_path / "simulation.json"
    simulation_path.write_text(json.dumps(_ready_simulation()), encoding="utf-8")
    state_dir = tmp_path / "state"

    exit_code = main(
        [
            "--simulation",
            str(simulation_path),
            "--state-dir",
            str(state_dir),
            "--operator",
            "release-operator",
            "--bundle-id",
            "governance-bundle",
            "--bundle-version",
            "2026.07.04",
            "--bundle-channel",
            "stable",
            "--bundle-digest",
            "sha256:abc123",
            "--created-at",
            "2026-07-04T05:00:00Z",
        ]
    )
    assert exit_code == 0

    action = json.loads(
        next((state_dir / "governance-rollout" / "actions").iterdir()).read_text(
            encoding="utf-8"
        )
    )
    assert action["created_at"] == "2026-07-04T05:00:00Z"
