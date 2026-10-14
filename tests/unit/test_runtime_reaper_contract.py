import json
import signal
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from tests.support.argparse_output import without_ansi


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def test_runtime_reaper_main_reports_no_stale_resources(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.runtime_reaper import main

    assert main(["--runtime-root", str(tmp_path / "runtime")]) == 0
    assert capsys.readouterr().out == "runtime reaper found no stale broker-owned resources\n"


def test_runtime_reaper_main_help_pins_cli_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.runtime_reaper import main

    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "\nReap mcp-broker runtime leftovers\n\noptions:" in without_ansi(output)
    assert "--runtime-root RUNTIME_ROOT" in without_ansi(output)


def test_runtime_reaper_main_requires_runtime_root(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.runtime_reaper import main

    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 2
    assert "--runtime-root" in without_ansi(capsys.readouterr().err)


def test_runtime_reaper_main_reports_stale_pidfile(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.runtime_reaper import RuntimePaths, main

    runtime_root = tmp_path / "runtime"
    paths = RuntimePaths.from_root(runtime_root)
    paths.upstream_pid_dir.mkdir(parents=True, exist_ok=True)
    (paths.upstream_pid_dir / "dead.json").write_text(
        json.dumps(
            {
                "broker_pid": 999_998,
                "name": "dead",
                "owner": "mcp-broker",
                "pid": 999_999,
                "process_group_id": 999_999,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    assert main(["--runtime-root", str(runtime_root)]) == 0
    assert capsys.readouterr().out == "reaped stale pidfiles: dead\n"


def test_write_process_metadata_persists_contract_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, write_process_metadata

    # Pinned so the expected bytes do not depend on the host's process table.
    monkeypatch.setattr(runtime_reaper, "process_start_time", lambda pid: f"t{pid}")
    paths = RuntimePaths.from_root(tmp_path / "runtime")

    metadata_path = write_process_metadata(
        paths,
        name="upstream-alpha",
        pid=101,
        process_group_id=202,
        broker_pid=303,
    )

    assert metadata_path == paths.upstream_pid_dir / "upstream-alpha.json"
    assert metadata_path.read_bytes() == (
        b'{"broker_pid": 303, "broker_start_time": "t303", '
        b'"name": "upstream-alpha", "owner": "mcp-broker", "pid": 101, '
        b'"process_group_id": 202, "start_time": "t101"}\n'
    )
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == {
        "broker_pid": 303,
        "broker_start_time": "t303",
        "name": "upstream-alpha",
        "owner": "mcp-broker",
        "pid": 101,
        "process_group_id": 202,
        "start_time": "t101",
    }


def test_write_process_metadata_records_a_null_identity_it_cannot_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable identity is written explicitly, not omitted."""
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, write_process_metadata

    monkeypatch.setattr(runtime_reaper, "process_start_time", lambda pid: None)

    metadata_path = write_process_metadata(
        RuntimePaths.from_root(tmp_path / "runtime"),
        name="upstream-alpha",
        pid=101,
        process_group_id=202,
        broker_pid=303,
    )

    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert payload["start_time"] is None
    assert payload["broker_start_time"] is None
    assert "start_time" in payload and "broker_start_time" in payload


def test_write_socket_metadata_persists_contract_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, write_socket_metadata

    monkeypatch.setattr(runtime_reaper, "process_start_time", lambda pid: f"t{pid}")
    paths = RuntimePaths.from_root(tmp_path / "runtime")

    metadata_path = write_socket_metadata(
        paths,
        socket_name="broker.sock",
        pid=101,
        broker_pid=303,
    )

    assert metadata_path == paths.socket_owner_dir / "broker.sock.json"
    assert metadata_path.read_bytes() == (
        b'{"broker_pid": 303, "owner": "mcp-broker", "pid": 101, '
        b'"socket_name": "broker.sock", "start_time": "t101"}\n'
    )
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == {
        "broker_pid": 303,
        "owner": "mcp-broker",
        "pid": 101,
        "socket_name": "broker.sock",
        "start_time": "t101",
    }


def test_runtime_paths_ensure_creates_full_layout(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import RuntimePaths

    paths = RuntimePaths.from_root(tmp_path / "runtime")

    paths.ensure()

    assert sorted(
        path.relative_to(paths.root).as_posix()
        for path in paths.root.rglob("*")
        if path.is_dir()
    ) == [
        "logs",
        "run",
        "run/sockets",
        "run/upstreams",
        "secrets",
        "sockets",
        "state",
        "state/upstreams",
    ]


def test_runtime_reaper_uses_recorded_broker_pid_and_process_group_id_for_orphan_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper, write_process_metadata

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    metadata_path = write_process_metadata(
        paths,
        name="orphaned-upstream",
        pid=111,
        broker_pid=222,
        process_group_id=333,
    )
    process_checks: list[int] = []
    process_group_checks: list[int] = []
    killed_groups: list[int] = []

    def process_exists(pid: int) -> bool:
        process_checks.append(pid)
        return pid == 111

    def process_group_exists(process_group_id: int) -> bool:
        process_group_checks.append(process_group_id)
        return process_group_id == 333

    monkeypatch.setattr(runtime_reaper, "_process_exists", process_exists)
    monkeypatch.setattr(runtime_reaper, "_process_group_exists", process_group_exists)
    monkeypatch.setattr(runtime_reaper, "_kill_process_group", killed_groups.append)

    report = RuntimeReaper(paths).reap()

    assert process_checks == [222]
    assert process_group_checks == [333]
    assert killed_groups == [333]
    assert report.killed_orphans == ("orphaned-upstream",)
    assert not metadata_path.exists()


def test_runtime_reaper_falls_back_to_pid_for_legacy_upstream_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.upstream_pid_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = paths.upstream_pid_dir / "legacy.json"
    metadata_path.write_bytes(
        b'{"name": "legacy", "owner": "mcp-broker", "pid": 777}\n'
    )
    process_checks: list[int] = []
    process_group_checks: list[int] = []

    def process_exists(pid: int) -> bool:
        process_checks.append(pid)
        return False

    def process_group_exists(process_group_id: int) -> bool:
        process_group_checks.append(process_group_id)
        return False

    monkeypatch.setattr(runtime_reaper, "_process_exists", process_exists)
    monkeypatch.setattr(runtime_reaper, "_process_group_exists", process_group_exists)

    report = RuntimeReaper(paths).reap()

    assert process_checks == [777, 777]
    assert process_group_checks == [777]
    assert report.stale_pidfiles == ("legacy",)
    assert not metadata_path.exists()


def test_runtime_reaper_pidfile_cleanup_tolerates_concurrent_orphan_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper, write_process_metadata

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    metadata_path = write_process_metadata(
        paths,
        name="orphaned-upstream",
        pid=111,
        broker_pid=222,
        process_group_id=333,
    )
    original_unlink = Path.unlink
    unlink_missing_ok_values: list[object] = []

    def unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path == metadata_path:
            unlink_missing_ok_values.append(missing_ok)
            if missing_ok is not True:
                raise FileNotFoundError(path)
        original_unlink(path, missing_ok=True)

    monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: pid == 111)
    monkeypatch.setattr(runtime_reaper, "_process_group_exists", lambda process_group_id: True)
    monkeypatch.setattr(runtime_reaper, "_kill_process_group", lambda process_group_id: None)
    monkeypatch.setattr(Path, "unlink", unlink)

    report = RuntimeReaper(paths).reap()

    assert unlink_missing_ok_values == [True]
    assert report.killed_orphans == ("orphaned-upstream",)
    assert not metadata_path.exists()


def test_runtime_reaper_pidfile_cleanup_tolerates_concurrent_stale_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper, write_process_metadata

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    metadata_path = write_process_metadata(
        paths,
        name="stale-upstream",
        pid=111,
        broker_pid=222,
        process_group_id=333,
    )
    original_unlink = Path.unlink
    unlink_missing_ok_values: list[object] = []

    def unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path == metadata_path:
            unlink_missing_ok_values.append(missing_ok)
            if missing_ok is not True:
                raise FileNotFoundError(path)
        original_unlink(path, missing_ok=True)

    monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: False)
    monkeypatch.setattr(runtime_reaper, "_process_group_exists", lambda process_group_id: False)
    monkeypatch.setattr(Path, "unlink", unlink)

    report = RuntimeReaper(paths).reap()

    assert unlink_missing_ok_values == [True]
    assert report.stale_pidfiles == ("stale-upstream",)
    assert not metadata_path.exists()


def test_runtime_reaper_skips_non_owned_upstream_and_socket_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    foreign_pid = paths.upstream_pid_dir / "foreign.json"
    foreign_socket_metadata = paths.socket_owner_dir / "foreign.sock.json"
    foreign_socket = paths.sockets_dir / "foreign.sock"
    foreign_pid.write_bytes(
        b'{"name": "foreign", "owner": "other-owner", "pid": 888}\n'
    )
    foreign_socket_metadata.write_bytes(
        b'{"owner": "other-owner", "pid": 999, "socket_name": "foreign.sock"}\n'
    )
    foreign_socket.write_text("foreign socket placeholder", encoding="utf-8")

    def process_exists(pid: int) -> bool:
        raise AssertionError(f"non-owned pid should not be probed: {pid}")

    monkeypatch.setattr(runtime_reaper, "_process_exists", process_exists)

    report = RuntimeReaper(paths).reap()

    assert report.stale_pidfiles == ()
    assert report.killed_orphans == ()
    assert report.stale_sockets == ()
    assert foreign_pid.exists()
    assert foreign_socket_metadata.exists()
    assert foreign_socket.exists()


def test_runtime_reaper_foreign_upstream_metadata_does_not_block_owned_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    foreign_pid = paths.upstream_pid_dir / "aaa-foreign.json"
    owned_pid = paths.upstream_pid_dir / "bbb-owned.json"
    foreign_pid.write_bytes(
        b'{"name": "foreign", "owner": "other-owner", "pid": 888}\n'
    )
    owned_pid.write_bytes(
        b'{"name": "owned", "owner": "mcp-broker", "pid": 999}\n'
    )

    monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: False)
    monkeypatch.setattr(runtime_reaper, "_process_group_exists", lambda process_group_id: False)

    report = RuntimeReaper(paths).reap()

    assert report.stale_pidfiles == ("owned",)
    assert foreign_pid.exists()
    assert not owned_pid.exists()


def test_runtime_reaper_foreign_socket_metadata_does_not_block_owned_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    foreign_metadata = paths.socket_owner_dir / "aaa-foreign.sock.json"
    owned_metadata = paths.socket_owner_dir / "bbb-owned.sock.json"
    owned_socket = paths.sockets_dir / "bbb-owned.sock"
    foreign_metadata.write_bytes(
        b'{"owner": "other-owner", "pid": 888, "socket_name": "aaa-foreign.sock"}\n'
    )
    owned_metadata.write_bytes(
        b'{"owner": "mcp-broker", "pid": 999, "socket_name": "bbb-owned.sock"}\n'
    )
    owned_socket.write_text("stale socket placeholder", encoding="utf-8")

    monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: False)

    report = RuntimeReaper(paths).reap()

    assert report.stale_sockets == ("bbb-owned.sock",)
    assert foreign_metadata.exists()
    assert not owned_metadata.exists()
    assert not owned_socket.exists()


def test_runtime_reaper_reports_resources_in_stable_sorted_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    (paths.upstream_pid_dir / "zeta.json").write_bytes(
        b'{"broker_pid": 910, "name": "zeta", "owner": "mcp-broker", '
        b'"pid": 911, "process_group_id": 912}\n'
    )
    (paths.upstream_pid_dir / "alpha.json").write_bytes(
        b'{"broker_pid": 810, "name": "alpha", "owner": "mcp-broker", '
        b'"pid": 811, "process_group_id": 812}\n'
    )
    (paths.socket_owner_dir / "zeta.sock.json").write_bytes(
        b'{"owner": "mcp-broker", "pid": 701, "socket_name": "zeta.sock"}\n'
    )
    (paths.socket_owner_dir / "alpha.sock.json").write_bytes(
        b'{"owner": "mcp-broker", "pid": 601, "socket_name": "alpha.sock"}\n'
    )

    monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: False)
    monkeypatch.setattr(runtime_reaper, "_process_group_exists", lambda process_group_id: False)

    report = RuntimeReaper(paths).reap()

    assert report.stale_pidfiles == ("alpha", "zeta")
    assert report.stale_sockets == ("alpha.sock", "zeta.sock")


def test_runtime_reaper_removes_stale_owned_socket_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper, write_socket_metadata

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    socket_path = paths.sockets_dir / "broker.sock"
    socket_path.write_text("stale socket placeholder", encoding="utf-8")
    metadata_path = write_socket_metadata(paths, socket_name="broker.sock", pid=444, broker_pid=555)
    process_checks: list[int] = []

    def process_exists(pid: int) -> bool:
        process_checks.append(pid)
        return False

    monkeypatch.setattr(runtime_reaper, "_process_exists", process_exists)

    report = RuntimeReaper(paths).reap()

    assert process_checks == [444]
    assert report.stale_sockets == ("broker.sock",)
    assert not socket_path.exists()
    assert not metadata_path.exists()


def test_runtime_reaper_socket_cleanup_tolerates_concurrent_metadata_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper, write_socket_metadata

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    socket_path = paths.sockets_dir / "broker.sock"
    socket_path.write_text("stale socket placeholder", encoding="utf-8")
    metadata_path = write_socket_metadata(paths, socket_name="broker.sock", pid=444, broker_pid=555)
    original_unlink = Path.unlink
    unlink_missing_ok_values: list[object] = []

    def unlink(path: Path, *, missing_ok: bool = False) -> None:
        if path == metadata_path:
            unlink_missing_ok_values.append(missing_ok)
            if missing_ok is not True:
                raise FileNotFoundError(path)
        original_unlink(path, missing_ok=True)

    monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: False)
    monkeypatch.setattr(Path, "unlink", unlink)

    report = RuntimeReaper(paths).reap()

    assert unlink_missing_ok_values == [True]
    assert report.stale_sockets == ("broker.sock",)
    assert not socket_path.exists()
    assert not metadata_path.exists()


def test_format_report_orders_all_resource_categories() -> None:
    from mcp_broker.runtime_reaper import ReapReport, format_report

    report = ReapReport(
        stale_pidfiles=("alpha", "zeta"),
        killed_orphans=("orphan-a", "orphan-b"),
        stale_sockets=("alpha.sock", "zeta.sock"),
    )

    assert format_report(report) == [
        "reaped stale pidfiles: alpha, zeta",
        "killed orphan process groups: orphan-a, orphan-b",
        "removed stale sockets: alpha.sock, zeta.sock",
    ]


def test_process_probes_use_signal_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_broker import runtime_reaper

    calls: list[tuple[str, int, signal.Signals | int]] = []

    def kill(pid: int, sig: signal.Signals | int) -> None:
        calls.append(("kill", pid, sig))

    def killpg(process_group_id: int, sig: signal.Signals | int) -> None:
        calls.append(("killpg", process_group_id, sig))

    monkeypatch.setattr(runtime_reaper.os, "kill", kill)
    monkeypatch.setattr(runtime_reaper.os, "killpg", killpg)

    assert runtime_reaper._process_exists(123) is True
    assert runtime_reaper._process_group_exists(456) is True
    assert calls == [("kill", 123, 0), ("killpg", 456, 0)]


@pytest.mark.parametrize(
    ("exception_type", "expected"),
    [
        (ProcessLookupError, False),
        (PermissionError, True),
    ],
)
def test_process_probe_exception_contract(
    monkeypatch: pytest.MonkeyPatch,
    exception_type: type[Exception],
    expected: bool,
) -> None:
    from mcp_broker import runtime_reaper

    def kill(pid: int, sig: signal.Signals | int) -> None:
        raise exception_type()

    def killpg(process_group_id: int, sig: signal.Signals | int) -> None:
        raise exception_type()

    monkeypatch.setattr(runtime_reaper.os, "kill", kill)
    monkeypatch.setattr(runtime_reaper.os, "killpg", killpg)

    assert runtime_reaper._process_exists(123) is expected
    assert runtime_reaper._process_group_exists(456) is expected


def test_kill_process_group_uses_sigkill_and_ignores_missing_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import runtime_reaper

    calls: list[tuple[int, signal.Signals | int]] = []

    def killpg(process_group_id: int, sig: signal.Signals | int) -> None:
        calls.append((process_group_id, sig))
        raise ProcessLookupError()

    monkeypatch.setattr(runtime_reaper.os, "killpg", killpg)

    runtime_reaper._kill_process_group(456)

    assert calls == [(456, signal.SIGKILL)]


def _write_identity_metadata(
    paths: object,
    *,
    name: str,
    pid: int,
    broker_pid: int,
    process_group_id: int,
    start_time: str | None,
    broker_start_time: str | None,
) -> Path:
    """A pidfile whose identity fields are chosen by the test, not the host."""
    from mcp_broker.runtime_reaper import RuntimePaths

    assert isinstance(paths, RuntimePaths)
    paths.upstream_pid_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = paths.upstream_pid_dir / f"{name}.json"
    metadata_path.write_text(
        json.dumps(
            {
                "broker_pid": broker_pid,
                "broker_start_time": broker_start_time,
                "name": name,
                "owner": "mcp-broker",
                "pid": pid,
                "process_group_id": process_group_id,
                "start_time": start_time,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return metadata_path


class TestPidIdentity:
    """A live pid number is not proof that the recorded process still holds it."""

    def test_a_recycled_upstream_pid_is_reaped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_broker import runtime_reaper
        from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

        paths = RuntimePaths.from_root(tmp_path / "runtime")
        metadata_path = _write_identity_metadata(
            paths,
            name="recycled",
            pid=111,
            broker_pid=222,
            process_group_id=333,
            start_time="spawned-at-t1",
            broker_start_time="spawned-at-t1",
        )
        monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: True)
        monkeypatch.setattr(runtime_reaper, "_process_group_exists", lambda pgid: False)
        monkeypatch.setattr(
            runtime_reaper,
            "process_start_time",
            lambda pid: "spawned-at-t9" if pid == 111 else "spawned-at-t1",
        )

        report = RuntimeReaper(paths).reap()

        assert report.stale_pidfiles == ("recycled",)
        assert report.killed_orphans == ()
        assert not metadata_path.exists()

    def test_a_recycled_broker_pid_does_not_hide_a_live_orphan_group(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_broker import runtime_reaper
        from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

        paths = RuntimePaths.from_root(tmp_path / "runtime")
        metadata_path = _write_identity_metadata(
            paths,
            name="orphaned",
            pid=111,
            broker_pid=222,
            process_group_id=333,
            start_time="spawned-at-t1",
            broker_start_time="spawned-at-t1",
        )
        killed: list[int] = []
        monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: True)
        monkeypatch.setattr(runtime_reaper, "_process_group_exists", lambda pgid: True)
        monkeypatch.setattr(runtime_reaper, "_kill_process_group", killed.append)
        # The broker's recorded pid now belongs to something else entirely.
        monkeypatch.setattr(
            runtime_reaper,
            "process_start_time",
            lambda pid: "spawned-at-t9" if pid == 222 else "spawned-at-t1",
        )

        report = RuntimeReaper(paths).reap()

        assert killed == [333]
        assert report.killed_orphans == ("orphaned",)
        assert report.stale_pidfiles == ()
        assert not metadata_path.exists()

    def test_a_matching_identity_protects_the_live_upstream(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_broker import runtime_reaper
        from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

        paths = RuntimePaths.from_root(tmp_path / "runtime")
        metadata_path = _write_identity_metadata(
            paths,
            name="live",
            pid=111,
            broker_pid=222,
            process_group_id=333,
            start_time="spawned-at-t1",
            broker_start_time="spawned-at-t1",
        )
        monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: True)
        monkeypatch.setattr(runtime_reaper, "_process_group_exists", lambda pgid: False)
        monkeypatch.setattr(runtime_reaper, "process_start_time", lambda pid: "spawned-at-t1")

        report = RuntimeReaper(paths).reap()

        assert report.stale_pidfiles == ()
        assert report.killed_orphans == ()
        assert metadata_path.exists()

    def test_an_unreadable_identity_keeps_the_liveness_behaviour(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Never destroy runtime state on a platform that cannot answer."""
        from mcp_broker import runtime_reaper
        from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

        paths = RuntimePaths.from_root(tmp_path / "runtime")
        metadata_path = _write_identity_metadata(
            paths,
            name="unknown-identity",
            pid=111,
            broker_pid=222,
            process_group_id=333,
            start_time="spawned-at-t1",
            broker_start_time="spawned-at-t1",
        )
        monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: True)
        monkeypatch.setattr(runtime_reaper, "_process_group_exists", lambda pgid: False)
        monkeypatch.setattr(runtime_reaper, "process_start_time", lambda pid: None)

        report = RuntimeReaper(paths).reap()

        assert report.stale_pidfiles == ()
        assert metadata_path.exists()

    def test_legacy_metadata_without_identity_still_trusts_a_live_pid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Files written before identity existed must stay reapable and safe."""
        from mcp_broker import runtime_reaper
        from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

        paths = RuntimePaths.from_root(tmp_path / "runtime")
        paths.upstream_pid_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = paths.upstream_pid_dir / "legacy-live.json"
        metadata_path.write_bytes(
            b'{"broker_pid": 222, "name": "legacy-live", "owner": "mcp-broker", '
            b'"pid": 111, "process_group_id": 333}\n'
        )
        monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: True)
        monkeypatch.setattr(runtime_reaper, "_process_group_exists", lambda pgid: False)
        monkeypatch.setattr(runtime_reaper, "process_start_time", lambda pid: "anything")

        report = RuntimeReaper(paths).reap()

        assert report.stale_pidfiles == ()
        assert report.killed_orphans == ()
        assert metadata_path.exists()

    def test_a_recycled_socket_pid_removes_the_socket(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_broker import runtime_reaper
        from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

        paths = RuntimePaths.from_root(tmp_path / "runtime")
        paths.ensure()
        socket_path = paths.sockets_dir / "broker.sock"
        socket_path.touch()
        metadata_path = paths.socket_owner_dir / "broker.sock.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "broker_pid": 222,
                    "owner": "mcp-broker",
                    "pid": 111,
                    "socket_name": "broker.sock",
                    "start_time": "spawned-at-t1",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: True)
        monkeypatch.setattr(runtime_reaper, "process_start_time", lambda pid: "spawned-at-t9")

        report = RuntimeReaper(paths).reap()

        assert report.stale_sockets == ("broker.sock",)
        assert not socket_path.exists()
        assert not metadata_path.exists()

    def test_a_matching_socket_identity_keeps_the_socket(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_broker import runtime_reaper
        from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

        paths = RuntimePaths.from_root(tmp_path / "runtime")
        paths.ensure()
        socket_path = paths.sockets_dir / "broker.sock"
        socket_path.touch()
        metadata_path = paths.socket_owner_dir / "broker.sock.json"
        metadata_path.write_text(
            json.dumps(
                {
                    "broker_pid": 222,
                    "owner": "mcp-broker",
                    "pid": 111,
                    "socket_name": "broker.sock",
                    "start_time": "spawned-at-t1",
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(runtime_reaper, "_process_exists", lambda pid: True)
        monkeypatch.setattr(runtime_reaper, "process_start_time", lambda pid: "spawned-at-t1")

        report = RuntimeReaper(paths).reap()

        assert report.stale_sockets == ()
        assert socket_path.exists()
        assert metadata_path.exists()


class TestProcessStartTime:
    """The identity reader itself, on both platforms and on its failure paths."""

    def test_linux_reads_the_starttime_field(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_broker import runtime_reaper

        proc_root = tmp_path / "proc"
        (proc_root / "4242").mkdir(parents=True)
        (proc_root / "4242" / "stat").write_text(
            "4242 (a name with ) and spaces) S 1 4242 4242 0 -1 4194560 100 0 0 0 "
            "1 2 3 4 20 0 1 0 987654 12345\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(runtime_reaper, "_PROC_ROOT", proc_root)

        assert runtime_reaper._linux_start_time(4242) == "987654"

    def test_linux_returns_none_for_an_absent_or_malformed_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_broker import runtime_reaper

        proc_root = tmp_path / "proc"
        (proc_root / "4242").mkdir(parents=True)
        (proc_root / "4242" / "stat").write_text("4242 (truncated) S 1\n", encoding="utf-8")
        monkeypatch.setattr(runtime_reaper, "_PROC_ROOT", proc_root)

        assert runtime_reaper._linux_start_time(4242) is None
        assert runtime_reaper._linux_start_time(9999) is None

    def test_darwin_reads_ps_and_reports_failure_as_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import subprocess as subprocess_module

        from mcp_broker import runtime_reaper

        class Done:
            def __init__(self, returncode: int, stdout: str) -> None:
                self.returncode = returncode
                self.stdout = stdout

        monkeypatch.setattr(
            subprocess_module,
            "run",
            lambda *args, **kwargs: Done(0, "Fri Sep 18 10:25:52 2026\n"),
        )
        assert runtime_reaper._darwin_start_time(4242) == "Fri Sep 18 10:25:52 2026"

        monkeypatch.setattr(
            subprocess_module, "run", lambda *args, **kwargs: Done(1, "")
        )
        assert runtime_reaper._darwin_start_time(4242) is None

        def explode(*args: object, **kwargs: object) -> object:
            raise OSError("ps is not installed")

        monkeypatch.setattr(subprocess_module, "run", explode)
        assert runtime_reaper._darwin_start_time(4242) is None

    def test_the_platform_picks_the_reader(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from mcp_broker import runtime_reaper

        monkeypatch.setattr(runtime_reaper, "_linux_start_time", lambda pid: f"linux:{pid}")
        monkeypatch.setattr(runtime_reaper, "_darwin_start_time", lambda pid: f"darwin:{pid}")

        monkeypatch.setattr(runtime_reaper.sys, "platform", "linux")
        assert runtime_reaper.process_start_time(7) == "linux:7"

        monkeypatch.setattr(runtime_reaper.sys, "platform", "darwin")
        assert runtime_reaper.process_start_time(7) == "darwin:7"

    def test_nonpositive_pids_have_no_identity(self) -> None:
        from mcp_broker.runtime_reaper import process_start_time

        assert process_start_time(0) is None
        assert process_start_time(-1) is None


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (0, " \tFri Sep 18 10:25:52 2026\n ", "Fri Sep 18 10:25:52 2026"),
        (0, "", None),
        (0, " \t\n", None),
        (1, "Fri Sep 18 10:25:52 2026\n", None),
        (2, "Fri Sep 18 10:25:52 2026\n", None),
        (-9, "Fri Sep 18 10:25:52 2026\n", None),
    ],
)
def test_darwin_start_time_pins_ps_contract_and_result(
    monkeypatch: pytest.MonkeyPatch,
    returncode: int,
    stdout: str,
    expected: str | None,
) -> None:
    from mcp_broker import runtime_reaper

    argv = ["ps", "-o", "lstart=", "-p", "4242"]
    run = Mock(return_value=subprocess.CompletedProcess(argv, returncode, stdout))
    monkeypatch.setattr(runtime_reaper.subprocess, "run", run)

    assert runtime_reaper._darwin_start_time(4242) == expected
    run.assert_called_once_with(
        argv, capture_output=True, text=True, timeout=5, check=False
    )


@pytest.mark.parametrize(
    "error",
    [
        OSError("ps is unavailable"),
        subprocess.SubprocessError("ps failed"),
        subprocess.TimeoutExpired(cmd="ps", timeout=5),
    ],
    ids=["os-error", "subprocess-error", "timeout"],
)
def test_darwin_start_time_handles_ps_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    from mcp_broker import runtime_reaper

    run = Mock(side_effect=error)
    monkeypatch.setattr(runtime_reaper.subprocess, "run", run)

    assert runtime_reaper._darwin_start_time(4242) is None
    run.assert_called_once_with(
        ["ps", "-o", "lstart=", "-p", "4242"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def test_linux_start_time_reads_pid_stat_with_explicit_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp_broker import runtime_reaper

    proc_root = tmp_path / "proc"
    stat_path = proc_root / "4242" / "stat"
    stat_path.parent.mkdir(parents=True)
    stat_path.write_text(
        "4242 (caf\u00e9 with ) and spaces) S 1 4242 4242 0 -1 4194560 100 0 0 0 "
        "1 2 3 4 20 0 1 0 987654 12345\n",
        encoding="utf-8",
    )
    original_read_text = Path.read_text
    reads: list[tuple[Path, tuple[object, ...], dict[str, object]]] = []

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        reads.append((path, args, kwargs))
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(runtime_reaper, "_PROC_ROOT", proc_root)
    monkeypatch.setattr(Path, "read_text", read_text)

    assert runtime_reaper._linux_start_time(4242) == "987654"
    assert reads == [(stat_path, (), {"encoding": "utf-8"})]


@pytest.mark.parametrize("platform", ["linux", "darwin"])
@pytest.mark.parametrize("pid", [-1, 0, 1])
def test_process_start_time_rejects_nonpositive_pids_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, platform: str, pid: int
) -> None:
    from mcp_broker import runtime_reaper

    stat_path = tmp_path / "1" / "stat"
    stat_path.parent.mkdir()
    stat_path.write_text(
        "1 (init) S 0 1 1 0 -1 4194560 100 0 0 0 "
        "1 2 3 4 20 0 1 0 987654 12345\n",
        encoding="utf-8",
    )
    original_read_text = Path.read_text
    reads: list[Path] = []

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        reads.append(path)
        return original_read_text(path, *args, **kwargs)

    argv = ["ps", "-o", "lstart=", "-p", "1"]
    run = Mock(return_value=subprocess.CompletedProcess(argv, 0, "darwin-start\n"))
    monkeypatch.setattr(runtime_reaper, "_PROC_ROOT", tmp_path)
    monkeypatch.setattr(runtime_reaper.sys, "platform", platform)
    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(runtime_reaper.subprocess, "run", run)

    result = runtime_reaper.process_start_time(pid)

    if pid <= 0:
        assert result is None
        assert reads == []
        run.assert_not_called()
    elif platform == "linux":
        assert result == "987654"
        assert reads == [stat_path]
        run.assert_not_called()
    else:
        assert result == "darwin-start"
        assert reads == []
        run.assert_called_once_with(
            argv, capture_output=True, text=True, timeout=5, check=False
        )


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [
        ({}, None),
        ({"start_time": None}, None),
        ({"start_time": ""}, None),
        ({"start_time": 42}, None),
        ({"start_time": True}, None),
        ({"start_time": False}, None),
        ({"start_time": ["start"]}, None),
        ({"start_time": {"value": "start"}}, None),
        ({"start_time": " \t"}, " \t"),
        ({"start_time": "upstream-start", "broker_start_time": "broker-start"}, "upstream-start"),
    ],
)
def test_recorded_identity_accepts_only_nonempty_strings(
    metadata: dict[str, object], expected: str | None
) -> None:
    from mcp_broker.runtime_reaper import _recorded_identity

    assert _recorded_identity(metadata, "start_time") == expected
    assert _recorded_identity(metadata, "absent") is None


def test_runtime_reaper_live_socket_does_not_block_later_stale_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from mcp_broker import runtime_reaper

    paths = runtime_reaper.RuntimePaths.from_root(tmp_path / "runtime")
    paths.ensure()
    live_socket = paths.sockets_dir / "aaa-live.sock"
    stale_socket = paths.sockets_dir / "zzz-stale.sock"
    live_metadata = paths.socket_owner_dir / "aaa-live.sock.json"
    stale_metadata = paths.socket_owner_dir / "zzz-stale.sock.json"
    live_socket.write_bytes(b"live socket placeholder")
    stale_socket.write_bytes(b"stale socket placeholder")
    live_payload = b'{"owner": "mcp-broker", "pid": 101, "socket_name": "aaa-live.sock"}\n'
    live_metadata.write_bytes(live_payload)
    stale_metadata.write_bytes(
        b'{"owner": "mcp-broker", "pid": 202, "socket_name": "zzz-stale.sock"}\n'
    )
    probes: list[tuple[int, int]] = []

    def kill(pid: int, sig: int) -> None:
        assert sig == 0
        assert pid in (101, 202)
        probes.append((pid, sig))
        if pid == 202:
            raise ProcessLookupError(pid)

    monkeypatch.setattr(runtime_reaper.os, "kill", kill)

    report = runtime_reaper.RuntimeReaper(paths).reap()

    assert probes == [(101, 0), (202, 0)]
    assert report == runtime_reaper.ReapReport(stale_sockets=("zzz-stale.sock",))
    assert live_socket.read_bytes() == b"live socket placeholder"
    assert live_metadata.read_bytes() == live_payload
    assert not stale_socket.exists()
    assert not stale_metadata.exists()
