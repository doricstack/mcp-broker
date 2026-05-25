import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


pytestmark = [pytest.mark.live, pytest.mark.error_simulation]

ROOT = Path(__file__).resolve().parents[2]


def test_runtime_reaper_removes_dead_owned_pidfile(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import (
        RuntimePaths,
        RuntimeReaper,
        write_process_metadata,
    )

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    metadata_path = write_process_metadata(
        paths,
        name="dead-upstream",
        pid=999_999,
        process_group_id=999_999,
        broker_pid=999_998,
    )

    report = RuntimeReaper(paths).reap()

    assert report.stale_pidfiles == ("dead-upstream",)
    assert not metadata_path.exists()


def test_runtime_reaper_preserves_unowned_pidfile(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.upstream_pid_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = paths.upstream_pid_dir / "external.json"
    metadata_path.write_text(
        '{"owner": "other", "name": "external", "pid": 999999}',
        encoding="utf-8",
    )

    report = RuntimeReaper(paths).reap()

    assert report.stale_pidfiles == ()
    assert metadata_path.exists()


def test_runtime_reaper_preserves_live_owned_pidfile(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import (
        RuntimePaths,
        RuntimeReaper,
        write_process_metadata,
    )

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    metadata_path = write_process_metadata(
        paths,
        name="live-upstream",
        pid=os.getpid(),
        process_group_id=os.getpgid(os.getpid()),
        broker_pid=os.getpid(),
    )

    report = RuntimeReaper(paths).reap()

    assert report.stale_pidfiles == ()
    assert report.killed_orphans == ()
    assert metadata_path.exists()


def test_runtime_reaper_removes_stale_owned_socket(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import (
        RuntimePaths,
        RuntimeReaper,
        write_socket_metadata,
    )

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.sockets_dir.mkdir(parents=True, exist_ok=True)
    socket_path = paths.sockets_dir / "broker.sock"
    socket_path.touch()
    metadata_path = write_socket_metadata(
        paths,
        socket_name="broker.sock",
        pid=999_999,
        broker_pid=999_998,
    )

    report = RuntimeReaper(paths).reap()

    assert report.stale_sockets == ("broker.sock",)
    assert not socket_path.exists()
    assert not metadata_path.exists()


def test_runtime_reaper_preserves_live_owned_socket(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import (
        RuntimePaths,
        RuntimeReaper,
        write_socket_metadata,
    )

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.sockets_dir.mkdir(parents=True, exist_ok=True)
    socket_path = paths.sockets_dir / "broker.sock"
    socket_path.touch()
    try:
        write_socket_metadata(
            paths,
            socket_name="broker.sock",
            pid=os.getpid(),
            broker_pid=os.getpid(),
        )

        report = RuntimeReaper(paths).reap()

        assert report.stale_sockets == ()
        assert socket_path.exists()
    finally:
        if socket_path.exists():
            socket_path.unlink()


def test_runtime_reaper_preserves_unowned_socket_metadata(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import RuntimePaths, RuntimeReaper

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    paths.socket_owner_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = paths.socket_owner_dir / "external.sock.json"
    metadata_path.write_text(
        '{"owner": "other", "pid": 999999, "socket_name": "external.sock"}',
        encoding="utf-8",
    )

    report = RuntimeReaper(paths).reap()

    assert report.stale_sockets == ()
    assert metadata_path.exists()


def test_runtime_reaper_kills_broker_owned_orphan_group(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import (
        RuntimePaths,
        RuntimeReaper,
        write_process_metadata,
    )

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    metadata_path = write_process_metadata(
        paths,
        name="orphan-upstream",
        pid=process.pid,
        process_group_id=os.getpgid(process.pid),
        broker_pid=999_998,
    )

    try:
        report = RuntimeReaper(paths).reap()

        process.wait(timeout=2)

        assert report.killed_orphans == ("orphan-upstream",)
        assert process.returncode is not None
        assert not metadata_path.exists()
    finally:
        if process.poll() is None:
            os.kill(process.pid, signal.SIGKILL)


def test_runtime_reaper_kills_live_group_when_recorded_parent_exited(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import (
        RuntimePaths,
        RuntimeReaper,
        write_process_metadata,
    )

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    child_pid_path = tmp_path / "child.pid"
    process_group_path = tmp_path / "process-group.pid"
    launcher = _orphan_child_launcher(tmp_path)
    subprocess.run(
        [sys.executable, str(launcher), str(child_pid_path), str(process_group_path)],
        check=True,
        start_new_session=True,
    )
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    process_group_id = int(process_group_path.read_text(encoding="utf-8"))
    metadata_path = write_process_metadata(
        paths,
        name="dead-parent-live-group",
        pid=process_group_id,
        process_group_id=process_group_id,
        broker_pid=999_998,
    )

    try:
        report = RuntimeReaper(paths).reap()

        _wait_for_process_exit(child_pid)

        assert report.killed_orphans == ("dead-parent-live-group",)
        assert not metadata_path.exists()
        assert not _process_exists(child_pid)
    finally:
        if _process_exists(child_pid):
            _kill_process_group_for_pid(child_pid)


def test_make_broker_reap_invokes_runtime_reaper(tmp_path: Path) -> None:
    from mcp_broker.runtime_reaper import RuntimePaths, write_process_metadata

    runtime_root = tmp_path / "runtime"
    paths = RuntimePaths.from_root(runtime_root)
    write_process_metadata(
        paths,
        name="make-stale",
        pid=999_999,
        process_group_id=999_999,
        broker_pid=999_998,
    )

    result = subprocess.run(
        ["make", "broker-reap", f"RUNTIME_ROOT={runtime_root}"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert "reaped stale pidfiles: make-stale" in result.stdout


def test_runtime_reaper_main_reports_no_stale_resources(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.runtime_reaper import main

    result = main(["--runtime-root", str(tmp_path / "runtime")])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == "runtime reaper found no stale broker-owned resources\n"


def test_runtime_reaper_process_probe_permission_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.runtime_reaper as runtime_reaper

    monkeypatch.setattr(
        runtime_reaper.os,
        "kill",
        lambda *_args: (_ for _ in ()).throw(PermissionError()),
    )
    assert runtime_reaper._process_exists(123) is True

    monkeypatch.setattr(
        runtime_reaper.os,
        "killpg",
        lambda *_args: (_ for _ in ()).throw(PermissionError()),
    )
    assert runtime_reaper._process_group_exists(123) is True

    monkeypatch.setattr(
        runtime_reaper.os,
        "killpg",
        lambda *_args: (_ for _ in ()).throw(ProcessLookupError()),
    )
    runtime_reaper._kill_process_group(123)


def test_make_broker_reap_cleans_upstream_after_daemon_crash(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    socket_path = Path("/tmp") / f"mcp-broker-crash-{os.getpid()}-{tmp_path.name}.sock"
    upstream_pid_path = tmp_path / "upstream.pid"
    daemon_ready_path = tmp_path / "daemon.ready"
    worker = _pid_reporting_mcp_worker(tmp_path)
    launcher = _crashing_daemon_launcher(tmp_path)
    daemon = subprocess.Popen(
        [
            sys.executable,
            str(launcher),
            str(runtime_root),
            str(socket_path),
            str(worker),
            str(upstream_pid_path),
            str(daemon_ready_path),
        ],
        cwd=ROOT,
        env=os.environ | {"PYTHONPATH": str(ROOT / "src")},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    upstream_pid: int | None = None

    try:
        _wait_for_path(daemon_ready_path)
        response = _socket_request(
            socket_path,
            {
                "jsonrpc": "2.0",
                "id": "crash-call",
                "method": "tools/call",
                "params": {"name": "crashy.ping", "arguments": {}},
            },
        )
        _wait_for_path(upstream_pid_path)
        upstream_pid = int(upstream_pid_path.read_text(encoding="utf-8"))

        assert response["id"] == "crash-call"
        assert response["result"]["content"][0]["text"] == "alive"
        assert _process_exists(upstream_pid)

        os.kill(daemon.pid, signal.SIGKILL)
        daemon.wait(timeout=2)
        assert _process_exists(upstream_pid)

        result = subprocess.run(
            ["make", "broker-reap", f"RUNTIME_ROOT={runtime_root}"],
            cwd=ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        _wait_for_process_exit(upstream_pid)

        assert "killed orphan process groups: crashy" in result.stdout
        assert not _process_exists(upstream_pid)
        assert not (runtime_root / "run" / "upstreams" / "crashy.json").exists()
    finally:
        if daemon.poll() is None:
            os.killpg(os.getpgid(daemon.pid), signal.SIGKILL)
            daemon.wait(timeout=2)
        if upstream_pid is None and upstream_pid_path.exists():
            upstream_pid = int(upstream_pid_path.read_text(encoding="utf-8"))
        if upstream_pid is not None and _process_exists(upstream_pid):
            _kill_process_group_for_pid(upstream_pid)
        socket_path.unlink(missing_ok=True)


def test_runtime_reaper_formats_report_for_each_cleanup_type() -> None:
    from mcp_broker.runtime_reaper import ReapReport, format_report

    report = ReapReport(
        stale_pidfiles=("dead",),
        killed_orphans=("orphan",),
        stale_sockets=("broker.sock",),
    )

    assert format_report(report) == [
        "reaped stale pidfiles: dead",
        "killed orphan process groups: orphan",
        "removed stale sockets: broker.sock",
    ]
    assert format_report(ReapReport()) == [
        "runtime reaper found no stale broker-owned resources"
    ]


def _crashing_daemon_launcher(tmp_path: Path) -> Path:
    path = tmp_path / "crashing_daemon_launcher.py"
    path.write_text(
        """
import os
from pathlib import Path
import signal
import sys

from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig, UpstreamConfig
from mcp_broker.daemon import BrokerDaemon

runtime_root = Path(sys.argv[1])
socket_path = Path(sys.argv[2])
worker_path = Path(sys.argv[3])
upstream_pid_path = Path(sys.argv[4])
daemon_ready_path = Path(sys.argv[5])

config = BrokerConfig(
    runtime=RuntimeConfig(
        root=runtime_root,
        socket_path=socket_path,
        log_dir=runtime_root / "logs",
        state_dir=runtime_root / "state",
        secrets_dir=runtime_root / "secrets",
    ),
    broker=BrokerSettings(),
    upstreams={
        "crashy": UpstreamConfig(
            name="crashy",
            command=sys.executable,
            args=[str(worker_path), str(upstream_pid_path)],
            mode="shared",
            transport="stdio",
            tool_prefix="crashy",
        )
    },
)
daemon = BrokerDaemon(runtime_root=runtime_root, socket_path=socket_path, broker_config=config)
daemon.start()
daemon_ready_path.write_text(str(os.getpid()), encoding="utf-8")
signal.pause()
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _pid_reporting_mcp_worker(tmp_path: Path) -> Path:
    path = tmp_path / "pid_reporting_mcp_worker.py"
    path.write_text(
        """
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

child_code = (
    "import signal, time\\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n"
    "time.sleep(60)\\n"
)
child = subprocess.Popen([sys.executable, "-c", child_code])
Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "ping",
                    "description": "ping",
                    "inputSchema": {"type": "object"},
                }
            ]
        }
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "alive"}]}
    else:
        result = {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "serverInfo": {"name": "crashy", "version": "test"},
        }
    print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _orphan_child_launcher(tmp_path: Path) -> Path:
    path = tmp_path / "orphan_child_launcher.py"
    path.write_text(
        """
import os
from pathlib import Path
import signal
import subprocess
import sys

child_code = (
    "import signal, time\\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\\n"
    "time.sleep(60)\\n"
)
child = subprocess.Popen([sys.executable, "-c", child_code])
Path(sys.argv[1]).write_text(str(child.pid), encoding="utf-8")
Path(sys.argv[2]).write_text(str(os.getpgid(os.getpid())), encoding="utf-8")
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _socket_request(socket_path: Path, payload: dict[str, object]) -> dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        raw = client.recv(65536)
    return json.loads(raw.decode("utf-8"))


def _wait_for_path(path: Path) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"path not created: {path}")


def _wait_for_process_exit(pid: int) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if not _process_exists(pid):
            return
        time.sleep(0.05)
    raise AssertionError(f"process still running: {pid}")


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _kill_process_group_for_pid(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except ProcessLookupError:
        return
