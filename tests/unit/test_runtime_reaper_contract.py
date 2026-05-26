import json
import signal
from pathlib import Path

import pytest


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
    assert "\nReap mcp-broker runtime leftovers\n\noptions:" in output
    assert "--runtime-root RUNTIME_ROOT" in output


def test_runtime_reaper_main_requires_runtime_root(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.runtime_reaper import main

    with pytest.raises(SystemExit) as exc_info:
        main([])

    assert exc_info.value.code == 2
    assert "--runtime-root" in capsys.readouterr().err


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


def test_write_process_metadata_persists_contract_fields(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import RuntimePaths, write_process_metadata

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
        b'{"broker_pid": 303, "name": "upstream-alpha", "owner": "mcp-broker", '
        b'"pid": 101, "process_group_id": 202}\n'
    )
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == {
        "broker_pid": 303,
        "name": "upstream-alpha",
        "owner": "mcp-broker",
        "pid": 101,
        "process_group_id": 202,
    }


def test_write_socket_metadata_persists_contract_fields(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import RuntimePaths, write_socket_metadata

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
        b'"socket_name": "broker.sock"}\n'
    )
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == {
        "broker_pid": 303,
        "owner": "mcp-broker",
        "pid": 101,
        "socket_name": "broker.sock",
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
