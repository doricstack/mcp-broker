from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest

from tests.support.argparse_output import without_ansi
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


def test_deployment_store_rejects_rollback_without_active_pointer(tmp_path: Path) -> None:
    from mcp_broker.deployments import DeploymentError, DeploymentStore

    store = DeploymentStore(tmp_path / "runtime" / "state")

    with pytest.raises(DeploymentError, match="active deployment pointer"):
        store.rollback()


def test_deployment_store_rejects_rollback_without_previous_pointer(tmp_path: Path) -> None:
    from mcp_broker.deployments import DeploymentError, DeploymentStore

    state_dir = tmp_path / "runtime" / "state"
    store = DeploymentStore(state_dir)
    store.record_deployment(write_signed_bundle(tmp_path / "first.json"))

    with pytest.raises(DeploymentError, match="previous deployment pointer"):
        store.rollback()


def test_deployment_store_rejects_rollback_when_previous_record_is_missing(
    tmp_path: Path,
) -> None:
    from mcp_broker.deployments import DeploymentError, DeploymentStore

    state_dir = tmp_path / "runtime" / "state"
    store = DeploymentStore(state_dir)
    first = store.record_deployment(write_signed_bundle(tmp_path / "first.json"))
    store.record_deployment(
        write_signed_bundle(tmp_path / "second.json", _minimal_bundle("team-local", "2026.07.02"))
    )
    Path(str(first["record_path"])).unlink()

    with pytest.raises(DeploymentError, match="deployment record not found"):
        store.rollback()


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


def test_deployment_store_recover_is_noop_without_deployments_dir(tmp_path: Path) -> None:
    from mcp_broker.deployments import DeploymentStore

    recovery = DeploymentStore(tmp_path / "runtime" / "state").recover()

    assert recovery == {
        "active_deployment_id": None,
        "recovered": False,
        "removed_partial_files": [],
    }


def test_deployment_store_recover_fails_when_records_dir_is_empty(tmp_path: Path) -> None:
    from mcp_broker.deployments import DeploymentError, DeploymentStore

    state_dir = tmp_path / "runtime" / "state"
    deployments_dir = state_dir / "deployments"
    (deployments_dir / "records").mkdir(parents=True)
    (deployments_dir / "active.json").write_text(
        json.dumps(
            {
                "deployment_id": "missing-deployment",
                "record_path": str(deployments_dir / "records" / "missing-deployment.json"),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DeploymentError, match="active deployment record"):
        DeploymentStore(state_dir).recover()


def test_deployment_store_recover_fails_when_active_record_missing_and_no_records_exist(
    tmp_path: Path,
) -> None:
    from mcp_broker.deployments import DeploymentError, DeploymentStore

    state_dir = tmp_path / "runtime" / "state"
    deployments_dir = state_dir / "deployments"
    deployments_dir.mkdir(parents=True)
    (deployments_dir / "active.json").write_text(
        json.dumps(
            {
                "deployment_id": "missing-deployment",
                "record_path": str(deployments_dir / "records" / "missing-deployment.json"),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DeploymentError, match="active deployment record"):
        DeploymentStore(state_dir).recover()


def test_deployment_store_recover_promotes_latest_record_when_active_pointer_missing(
    tmp_path: Path,
) -> None:
    from mcp_broker.deployments import DeploymentStore

    state_dir = tmp_path / "runtime" / "state"
    store = DeploymentStore(state_dir)
    first = store.record_deployment(write_signed_bundle(tmp_path / "first.json"))
    (state_dir / "deployments" / "active.json").unlink()

    recovery = store.recover()

    assert recovery == {
        "active_deployment_id": first["deployment_id"],
        "recovered": True,
        "removed_partial_files": [],
    }
    assert _read_json(state_dir / "deployments" / "active.json")["deployment_id"] == first[
        "deployment_id"
    ]


def test_deployment_store_dry_run_stage_does_not_write_state(tmp_path: Path) -> None:
    from mcp_broker.deployments import DeploymentStore

    state_dir = tmp_path / "runtime" / "state"
    bundle_path = write_signed_bundle(tmp_path / "bundle.json")

    report = DeploymentStore(state_dir).dry_run_stage(bundle_path)

    assert report["bundle_path"] == str(bundle_path)
    assert report["would_change_runtime_state"] is False
    assert not (state_dir / "deployments").exists()


def test_deployments_cli_reports_stage_dry_run_and_apply(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.deployments import main

    state_dir = tmp_path / "runtime" / "state"
    bundle_path = write_signed_bundle(tmp_path / "bundle.json")

    assert main(["stage", "--bundle", str(bundle_path), "--state-dir", str(state_dir), "--dry-run"]) == 0
    assert "deployment dry-run:" in capsys.readouterr().out

    assert main(["stage", "--bundle", str(bundle_path), "--state-dir", str(state_dir)]) == 0
    assert "deployment staged:" in capsys.readouterr().out


def test_deployments_cli_reports_rollback_and_recover(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.deployments import main

    state_dir = tmp_path / "runtime" / "state"
    first_bundle = write_signed_bundle(tmp_path / "first.json")
    second_bundle = write_signed_bundle(
        tmp_path / "second.json",
        _minimal_bundle("team-local", "2026.07.02"),
    )

    assert main(["stage", "--bundle", str(first_bundle), "--state-dir", str(state_dir)]) == 0
    capsys.readouterr()
    assert main(["stage", "--bundle", str(second_bundle), "--state-dir", str(state_dir)]) == 0
    capsys.readouterr()

    assert main(["rollback", "--state-dir", str(state_dir)]) == 0
    assert "deployment rolled back:" in capsys.readouterr().out

    assert main(["recover", "--state-dir", str(state_dir)]) == 0
    assert "deployment recovery:" in capsys.readouterr().out


def test_deployments_cli_reports_bundle_errors(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.deployments import main

    bundle_path = tmp_path / "bad.json"
    bundle_path.write_text("[]", encoding="utf-8")

    assert main(["stage", "--bundle", str(bundle_path), "--state-dir", str(tmp_path / "state")]) == 1
    assert "bundle file must contain a JSON object" in capsys.readouterr().out


def test_deployment_helpers_reject_non_object_pointer_json(tmp_path: Path) -> None:
    from mcp_broker.deployments import DeploymentError, _read_json

    pointer_path = tmp_path / "active.json"
    pointer_path.write_text("[]", encoding="utf-8")

    with pytest.raises(DeploymentError, match="expected JSON object"):
        _read_json(pointer_path)


@pytest.mark.error_simulation
def test_deployments_main_reports_unknown_dispatch_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.deployments as deployments

    monkeypatch.setattr(
        deployments,
        "_parse_args",
        lambda _argv: SimpleNamespace(
            deployment_command="unknown",
            state_dir=tmp_path / "state",
        ),
    )

    with pytest.raises(deployments.DeploymentError, match="unknown deployment command"):
        deployments.main([])


@pytest.mark.error_simulation
def test_deployments_module_entrypoint_exits_with_main_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle_path = write_signed_bundle(tmp_path / "bundle.json")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "deployments",
            "stage",
            "--bundle",
            str(bundle_path),
            "--state-dir",
            str(tmp_path / "state"),
            "--dry-run",
        ],
    )

    module_name = "mcp_broker.deployments"
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


# --- the CLI contract ----------------------------------------------------------


def _stage_argv(**overrides: str) -> list[str]:
    fields = {"--bundle": "/tmp/bundle.json", "--state-dir": "/tmp/state"}
    fields.update(overrides)
    argv = ["stage"]
    for flag, value in fields.items():
        argv += [flag, value]
    return argv


def test_parse_args_stage_populates_every_declared_field() -> None:
    from mcp_broker.deployments import _parse_args

    args = _parse_args(_stage_argv())

    assert args.deployment_command == "stage"
    assert args.bundle == Path("/tmp/bundle.json")
    assert args.state_dir == Path("/tmp/state")
    assert args.dry_run is False


def test_parse_args_stage_paths_are_paths_not_strings() -> None:
    """type=Path on both: a str would reach the filesystem code unconverted."""
    from mcp_broker.deployments import _parse_args

    args = _parse_args(_stage_argv())
    assert isinstance(args.bundle, Path)
    assert isinstance(args.state_dir, Path)


def test_parse_args_dry_run_is_a_flag_that_defaults_to_false() -> None:
    """store_true: present means True, absent means False, and it takes no value."""
    from mcp_broker.deployments import _parse_args

    assert _parse_args(_stage_argv()).dry_run is False
    assert _parse_args(_stage_argv() + ["--dry-run"]).dry_run is True


@pytest.mark.parametrize("omitted", ["--bundle", "--state-dir"])
def test_parse_args_stage_requires_both_paths(omitted: str) -> None:
    from mcp_broker.deployments import _parse_args

    base = _stage_argv()
    index = base.index(omitted)
    argv = base[:index] + base[index + 2:]

    with pytest.raises(SystemExit) as exc:
        _parse_args(argv)
    assert exc.value.code == 2


@pytest.mark.parametrize("command", ["rollback", "recover"])
def test_parse_args_stateful_commands_take_a_state_dir(command: str) -> None:
    from mcp_broker.deployments import _parse_args

    args = _parse_args([command, "--state-dir", "/tmp/state"])

    assert args.deployment_command == command
    assert args.state_dir == Path("/tmp/state")


@pytest.mark.parametrize("command", ["rollback", "recover"])
def test_parse_args_stateful_commands_require_a_state_dir(command: str) -> None:
    from mcp_broker.deployments import _parse_args

    with pytest.raises(SystemExit) as exc:
        _parse_args([command])
    assert exc.value.code == 2


def test_parse_args_requires_a_subcommand() -> None:
    from mcp_broker.deployments import _parse_args

    with pytest.raises(SystemExit) as exc:
        _parse_args([])
    assert exc.value.code == 2


def test_parse_args_rejects_an_unknown_subcommand() -> None:
    from mcp_broker.deployments import _parse_args

    with pytest.raises(SystemExit) as exc:
        _parse_args(["destroy", "--state-dir", "/tmp/state"])
    assert exc.value.code == 2


def test_parse_args_rejects_an_unknown_flag() -> None:
    from mcp_broker.deployments import _parse_args

    with pytest.raises(SystemExit) as exc:
        _parse_args(_stage_argv() + ["--force"])
    assert exc.value.code == 2


def test_parse_args_subcommand_lands_in_the_deployment_command_attribute() -> None:
    """dest="deployment_command" is what main() dispatches on."""
    from mcp_broker.deployments import _parse_args

    for command, argv in (
        ("stage", _stage_argv()),
        ("rollback", ["rollback", "--state-dir", "/tmp/state"]),
        ("recover", ["recover", "--state-dir", "/tmp/state"]),
    ):
        assert getattr(_parse_args(argv), "deployment_command") == command


def test_parser_and_subcommand_help_text(capsys: pytest.CaptureFixture[str]) -> None:
    """Help is what an operator reads to use the tool. Exact matching, because an
    "XX"-wrapped literal still contains the original text."""
    from mcp_broker.deployments import _parse_args

    with pytest.raises(SystemExit) as exc:
        _parse_args(["--help"])
    assert exc.value.code == 0

    out = without_ansi(capsys.readouterr().out)
    assert "Manage mcp-broker deployment state\n" in out
    assert "Validate and record a bundle deployment" in out
    assert "Roll back to the previous deployment" in out
    assert "Recover deployment state after partial writes" in out
    assert "XX" not in out
    assert "manage mcp-broker deployment state" not in out
    assert "MANAGE MCP-BROKER DEPLOYMENT STATE" not in out


# --- the JSON helpers and the deployment id ------------------------------------


def test_write_json_atomic_formats_sorted_and_indented_with_a_trailing_newline(
    tmp_path: Path,
) -> None:
    from mcp_broker.deployments import _write_json_atomic

    target = tmp_path / "record.json"
    _write_json_atomic(target, {"b": 1, "a": 2})

    assert target.read_text(encoding="utf-8") == '{\n  "a": 2,\n  "b": 1\n}\n'


def test_write_json_atomic_creates_parents_and_leaves_no_temp_file(tmp_path: Path) -> None:
    from mcp_broker.deployments import _write_json_atomic

    # Two missing levels on purpose: mkdir(parents=False) still creates a single
    # missing directory, so a one-level path cannot catch a dropped parents=True.
    target = tmp_path / "deep" / "nested" / "record.json"
    _write_json_atomic(target, {"a": 1})

    assert target.is_file()
    assert sorted(p.name for p in target.parent.iterdir()) == ["record.json"]


def test_write_json_atomic_replaces_an_existing_file_entirely(tmp_path: Path) -> None:
    from mcp_broker.deployments import _write_json_atomic

    target = tmp_path / "record.json"
    target.write_text('{"stale": true}', encoding="utf-8")
    _write_json_atomic(target, {"fresh": True})

    assert json.loads(target.read_text(encoding="utf-8")) == {"fresh": True}


def test_read_json_rejects_valid_json_that_is_not_an_object(tmp_path: Path) -> None:
    from mcp_broker.deployments import DeploymentError, _read_json

    target = tmp_path / "record.json"
    target.write_text(json.dumps([1, 2]), encoding="utf-8")

    with pytest.raises(DeploymentError):
        _read_json(target)


def test_load_bundle_rejects_valid_json_that_is_not_an_object(tmp_path: Path) -> None:
    from mcp_broker.deployments import DeploymentError, _load_bundle

    bundle = tmp_path / "bundle.json"
    bundle.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")

    with pytest.raises(DeploymentError) as exc:
        _load_bundle(bundle)
    assert str(exc.value) == "bundle file must contain a JSON object"


def test_load_bundle_expands_a_user_relative_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """expanduser() is why a ~-prefixed bundle path works at all."""
    from mcp_broker.deployments import _load_bundle

    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "bundle.json").write_text(json.dumps({"id": "b"}), encoding="utf-8")

    assert _load_bundle(Path("~/bundle.json")) == {"id": "b"}


def test_deployment_id_joins_the_parts_and_truncates_the_checksum() -> None:
    """The id is bundle-version-checksum[:12]; the truncation length is part of it."""
    from mcp_broker.deployments import _deployment_id

    checksum = "0123456789abcdef0123456789abcdef"

    assert _deployment_id("bundle", "1.0.0", checksum) == "bundle-1.0.0-0123456789ab"


def test_deployment_id_replaces_every_unsafe_character_run_with_one_dash() -> None:
    """A deployment id becomes a path segment, so anything outside the safe set
    collapses rather than reaching the filesystem."""
    from mcp_broker.deployments import _deployment_id

    assert _deployment_id("my bundle/name", "1.0 beta", "abc") == "my-bundle-name-1.0-beta-abc"


def test_deployment_id_strips_leading_and_trailing_dashes() -> None:
    from mcp_broker.deployments import _deployment_id

    assert _deployment_id("/bundle", "1.0", "abc/") == "bundle-1.0-abc"


def test_deployment_id_keeps_dots_underscores_and_dashes() -> None:
    from mcp_broker.deployments import _deployment_id

    assert _deployment_id("a.b_c-d", "1.0", "abc") == "a.b_c-d-1.0-abc"


def test_pointer_carries_the_id_and_the_record_path(tmp_path: Path) -> None:
    from mcp_broker.deployments import _pointer

    record = tmp_path / "record.json"

    assert _pointer("dep-1", record) == {
        "deployment_id": "dep-1",
        "record_path": str(record),
    }


def test_read_pointer_returns_none_when_the_file_is_absent(tmp_path: Path) -> None:
    from mcp_broker.deployments import _read_pointer

    assert _read_pointer(tmp_path / "missing.json") is None


def test_read_pointer_stringifies_both_fields(tmp_path: Path) -> None:
    from mcp_broker.deployments import _read_pointer

    pointer = tmp_path / "active.json"
    pointer.write_text(json.dumps({"deployment_id": 7, "record_path": 8}), encoding="utf-8")

    assert _read_pointer(pointer) == {"deployment_id": "7", "record_path": "8"}


# --- the timestamp format and the printed messages -----------------------------


def test_utc_now_returns_a_z_suffixed_utc_timestamp() -> None:
    """The Z form is the stored format. A naive local clock produces no +00:00, so
    the replace never fires and the suffix silently disappears."""
    from datetime import datetime, timezone

    from mcp_broker.deployments import _utc_now

    stamp = _utc_now()

    assert stamp.endswith("Z"), stamp
    assert "+00:00" not in stamp
    assert not stamp.endswith("z"), "the suffix is capital Z"
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timezone.utc.utcoffset(None)


def test_stage_prints_the_dry_run_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from mcp_broker.deployments import DeploymentStore, _stage

    bundle = write_signed_bundle(tmp_path / "bundle.json")
    store = DeploymentStore(tmp_path / "state")
    args = SimpleNamespace(bundle=bundle, dry_run=True)

    assert _stage(args, store) == 0

    out = capsys.readouterr().out
    assert out.startswith("deployment dry-run: ")
    assert "XX" not in out


def test_stage_prints_the_staged_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from mcp_broker.deployments import DeploymentStore, _stage

    bundle = write_signed_bundle(tmp_path / "bundle.json")
    store = DeploymentStore(tmp_path / "state")
    args = SimpleNamespace(bundle=bundle, dry_run=False)

    assert _stage(args, store) == 0

    out = capsys.readouterr().out
    assert out.startswith("deployment staged: ")
    assert "XX" not in out


# --- the deployment id character rules -----------------------------------------


def test_deployment_id_replaces_uppercase_outside_the_safe_set_but_keeps_letters() -> None:
    """The safe class spans A-Z as well as a-z. Losing the uppercase range would
    rewrite every capitalised bundle name."""
    from mcp_broker.deployments import _deployment_id

    assert _deployment_id("Bundle", "V1", "ABC") == "Bundle-V1-ABC"


def test_deployment_id_strips_only_dashes_from_the_ends() -> None:
    """strip takes a set of characters, so a wider literal would also eat real ones."""
    from mcp_broker.deployments import _deployment_id

    assert _deployment_id("Xbundle", "1.0", "abcX") == "Xbundle-1.0-abcX"


def test_rollback_prints_the_rolled_back_message(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.deployments import DeploymentStore, _rollback

    from tests.support.bundles import minimal_bundle

    store = DeploymentStore(tmp_path / "state")
    store.record_deployment(write_signed_bundle(tmp_path / "first.json"))
    # A second, distinct deployment so there is a previous one to roll back to.
    second = minimal_bundle()
    second["version"] = "2026.07.02"
    store.record_deployment(write_signed_bundle(tmp_path / "second.json", second))

    assert _rollback(store) == 0

    out = capsys.readouterr().out
    assert out.startswith("deployment rolled back: ")
    assert "previous=" in out
    assert "XX" not in out


def test_recover_prints_the_recovery_message(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.deployments import DeploymentStore, _recover

    store = DeploymentStore(tmp_path / "state")
    store.record_deployment(write_signed_bundle(tmp_path / "bundle.json"))

    assert _recover(store) == 0

    out = capsys.readouterr().out
    assert out.startswith("deployment recovery: ")
    assert "active=" in out
    assert "recovered=" in out
    assert "XX" not in out
