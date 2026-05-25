import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.journey


def test_upstream_watchdog_startup_timeout_stops_unready_process(tmp_path: Path) -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_process import UpstreamProcessSupervisor
    from mcp_broker.upstream_state import UpstreamState

    worker = tmp_path / "slow_start.py"
    worker.write_text(
        """
import time

while True:
    time.sleep(0.05)
""".strip(),
        encoding="utf-8",
    )
    supervisor = UpstreamProcessSupervisor(
        upstream=UpstreamConfig(
            name="slow-start",
            command=sys.executable,
            args=[str(worker)],
            mode="shared",
            enabled=True,
            state_dir="upstreams/slow-start",
            tool_prefix="slow-start",
            startup_timeout_seconds=1,
        ),
        runtime_state_dir=tmp_path / "runtime" / "state",
    )

    with pytest.raises(TimeoutError, match="upstream startup timed out: slow-start"):
        supervisor.start(ready_check=lambda: False, poll_interval_seconds=0.01)

    assert supervisor.state == UpstreamState.BACKOFF
    assert supervisor.pid is None
    assert supervisor.status == "stopped"
    assert '"state": "backoff"' in supervisor.state_snapshot_path.read_text(encoding="utf-8")


def test_upstream_watchdog_drains_stdout_and_stderr_to_state_logs(tmp_path: Path) -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_process import UpstreamProcessSupervisor

    worker = tmp_path / "noisy.py"
    ready_file = tmp_path / "noisy-ready.txt"
    worker.write_text(
        """
import sys
import time
from pathlib import Path

Path(sys.argv[1]).write_text("ready", encoding="utf-8")
for index in range(2000):
    print(f"out-{index}", flush=True)
    print(f"err-{index}", file=sys.stderr, flush=True)
while True:
    time.sleep(0.05)
""".strip(),
        encoding="utf-8",
    )
    supervisor = UpstreamProcessSupervisor(
        upstream=UpstreamConfig(
            name="noisy",
            command=sys.executable,
            args=[str(worker), str(ready_file)],
            mode="shared",
            enabled=True,
            state_dir="upstreams/noisy",
            tool_prefix="noisy",
        ),
        runtime_state_dir=tmp_path / "runtime" / "state",
    )

    try:
        supervisor.start(
            ready_check=lambda: ready_file.exists(),
            poll_interval_seconds=0.01,
        )

        stdout_log = supervisor.state_dir / "stdout.log"
        stderr_log = supervisor.state_dir / "stderr.log"
        deadline = time.monotonic() + 2
        while (
            (
                "out-" not in _read_if_exists(stdout_log)
                or "err-" not in _read_if_exists(stderr_log)
            )
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        assert "out-" in stdout_log.read_text(encoding="utf-8")
        assert "err-" in stderr_log.read_text(encoding="utf-8")
        assert supervisor.status == "running"
    finally:
        supervisor.stop()


def test_upstream_watchdog_reaps_idle_process_after_timeout(tmp_path: Path) -> None:
    from mcp_broker.schema import ResourcePolicy

    unstarted = _build_sleeping_supervisor(
        tmp_path,
        name="idle-unstarted",
        resources=ResourcePolicy(idle_timeout_seconds=1),
    )
    supervisor = _start_sleeping_supervisor(
        tmp_path,
        name="idle",
        resources=ResourcePolicy(idle_timeout_seconds=1),
    )

    try:
        assert unstarted.reap_if_idle(monotonic_seconds=10.0) is False
        supervisor.record_activity(monotonic_seconds=10.0)

        assert supervisor.reap_if_idle(monotonic_seconds=10.5) is False
        assert supervisor.status == "running"

        assert supervisor.reap_if_idle(monotonic_seconds=11.1) is True
        assert supervisor.status == "stopped"
        assert supervisor.pid is None
    finally:
        supervisor.stop()


def test_upstream_watchdog_kills_cpu_spin_without_progress(tmp_path: Path) -> None:
    from mcp_broker.schema import ResourcePolicy
    from mcp_broker.upstream_state import UpstreamState

    unstarted = _build_sleeping_supervisor(
        tmp_path,
        name="spinner-unstarted",
        resources=ResourcePolicy(cpu_watchdog_percent=50, cpu_watchdog_seconds=2),
    )
    supervisor = _start_sleeping_supervisor(
        tmp_path,
        name="spinner",
        resources=ResourcePolicy(cpu_watchdog_percent=50, cpu_watchdog_seconds=2),
    )

    try:
        supervisor.record_activity(monotonic_seconds=20.0)

        assert (
            unstarted.kill_if_spinning(
                cpu_percent=80.0,
                sample_window_seconds=2.0,
                monotonic_seconds=22.0,
            )
            is False
        )
        assert supervisor.kill_if_spinning(
            cpu_percent=40.0,
            sample_window_seconds=2.0,
            monotonic_seconds=22.0,
        ) is False
        assert supervisor.kill_if_spinning(
            cpu_percent=80.0,
            sample_window_seconds=2.0,
            monotonic_seconds=21.0,
        ) is False
        assert supervisor.kill_if_spinning(
            cpu_percent=80.0,
            sample_window_seconds=1.0,
            monotonic_seconds=21.0,
        ) is False
        assert supervisor.status == "running"

        assert supervisor.kill_if_spinning(
            cpu_percent=80.0,
            sample_window_seconds=2.0,
            monotonic_seconds=22.1,
        ) is True
        assert supervisor.state == UpstreamState.FAILED
        assert supervisor.pid is None
    finally:
        supervisor.stop()


def test_upstream_watchdog_kills_spinning_process_group_from_sampler(
    tmp_path: Path,
) -> None:
    from mcp_broker.schema import ResourcePolicy
    from mcp_broker.upstream_state import UpstreamState

    unstarted = _build_sleeping_supervisor(
        tmp_path,
        name="sampled-spinner-unstarted",
        resources=ResourcePolicy(cpu_watchdog_percent=50, cpu_watchdog_seconds=2),
    )
    supervisor = _start_sleeping_supervisor(
        tmp_path,
        name="sampled-spinner",
        resources=ResourcePolicy(cpu_watchdog_percent=50, cpu_watchdog_seconds=2),
    )

    try:
        supervisor.record_activity(monotonic_seconds=40.0)

        assert unstarted.kill_if_process_group_spinning(
            sample_window_seconds=2.0,
            monotonic_seconds=42.1,
            cpu_sampler=lambda _pgid: 80.0,
        ) is False
        assert supervisor.kill_if_process_group_spinning(
            sample_window_seconds=2.0,
            monotonic_seconds=42.1,
            cpu_sampler=lambda _pgid: 80.0,
        ) is True
        assert supervisor.state == UpstreamState.FAILED
        assert supervisor.pid is None
    finally:
        supervisor.stop()


def test_upstream_watchdog_kills_process_group_over_memory_ceiling(
    tmp_path: Path,
) -> None:
    from mcp_broker.schema import ResourcePolicy
    from mcp_broker.upstream_state import UpstreamState

    unstarted = _build_sleeping_supervisor(
        tmp_path,
        name="read-store-unstarted",
        resources=ResourcePolicy(memory_ceiling_mb=1),
    )
    no_ceiling = _start_sleeping_supervisor(
        tmp_path,
        name="read-store-no-ceiling",
        resources=ResourcePolicy(),
    )
    supervisor = _start_sleeping_supervisor(
        tmp_path,
        name="read-store-ceiling",
        resources=ResourcePolicy(memory_ceiling_mb=1),
    )

    try:
        assert unstarted.kill_if_memory_over_ceiling(memory_mb=2.0) is False
        assert unstarted.kill_if_process_group_over_memory(
            memory_sampler=lambda _pgid: 2.0,
        ) is False
        assert no_ceiling.kill_if_process_group_over_memory(
            memory_sampler=lambda _pgid: 2.0,
        ) is False
        assert supervisor.kill_if_process_group_over_memory(
            memory_sampler=lambda _pgid: None,
        ) is False
        assert supervisor.kill_if_process_group_over_memory(
            memory_sampler=lambda _pgid: 0.5,
        ) is False
        assert supervisor.status == "running"

        assert supervisor.kill_if_process_group_over_memory(
            memory_sampler=lambda _pgid: 2.0,
        ) is True
        assert supervisor.state == UpstreamState.FAILED
        assert supervisor.pid is None
    finally:
        no_ceiling.stop()
        supervisor.stop()


def test_upstream_watchdog_restart_backoff_and_circuit_breaker(tmp_path: Path) -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.schema import RestartPolicy
    from mcp_broker.upstream_process import UpstreamProcessSupervisor
    from mcp_broker.upstream_state import UpstreamState

    worker = tmp_path / "restartable.py"
    worker.write_text(
        """
import time

while True:
    time.sleep(0.05)
""".strip(),
        encoding="utf-8",
    )
    supervisor = UpstreamProcessSupervisor(
        upstream=UpstreamConfig(
            name="restartable",
            command=sys.executable,
            args=[str(worker)],
            mode="shared",
            enabled=True,
            state_dir="upstreams/restartable",
            tool_prefix="restartable",
            restart=RestartPolicy(max_attempts=2, backoff_seconds=2),
        ),
        runtime_state_dir=tmp_path / "runtime" / "state",
    )

    try:
        assert supervisor.restart_after_failure(monotonic_seconds=30.0) is True
        first_pid = supervisor.pid
        assert first_pid is not None

        assert supervisor.restart_after_failure(monotonic_seconds=31.0) is False
        assert supervisor.state == UpstreamState.BACKOFF
        assert supervisor.pid == first_pid

        assert supervisor.restart_after_failure(monotonic_seconds=32.1) is True
        second_pid = supervisor.pid
        assert second_pid is not None
        assert second_pid != first_pid

        with pytest.raises(RuntimeError, match="restart circuit open: restartable"):
            supervisor.restart_after_failure(monotonic_seconds=35.0)
    finally:
        supervisor.stop()


def test_upstream_watchdog_startup_failure_stops_process_and_enters_backoff(
    tmp_path: Path,
) -> None:
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_process import UpstreamProcessSupervisor
    from mcp_broker.upstream_state import UpstreamState

    supervisor = UpstreamProcessSupervisor(
        upstream=UpstreamConfig(
            name="startup-exit",
            command=sys.executable,
            args=["-c", "raise SystemExit(0)"],
            mode="shared",
            enabled=True,
            state_dir="upstreams/startup-exit",
            tool_prefix="startup-exit",
        ),
        runtime_state_dir=tmp_path / "runtime" / "state",
    )

    with pytest.raises(RuntimeError, match="upstream exited during startup: startup-exit"):
        supervisor.start(ready_check=lambda: False, poll_interval_seconds=0.01)

    assert supervisor.state == UpstreamState.BACKOFF
    assert supervisor.pid is None


def test_upstream_watchdog_samples_process_group_cpu_percent() -> None:
    from mcp_broker.watchdog import sample_process_group_cpu_percent

    result = subprocess.CompletedProcess(
        args=["ps"],
        returncode=0,
        stdout=" 10.5\n 2.0\n",
        stderr="",
    )

    assert sample_process_group_cpu_percent(12345, runner=lambda _command: result) == 12.5


def test_upstream_watchdog_cpu_sampler_handles_missing_process_group() -> None:
    from mcp_broker.watchdog import sample_process_group_cpu_percent

    result = subprocess.CompletedProcess(
        args=["ps"],
        returncode=1,
        stdout="",
        stderr="",
    )

    assert sample_process_group_cpu_percent(12345, runner=lambda _command: result) == 0.0


def test_upstream_watchdog_cpu_sampler_runs_ps_for_real_process_group() -> None:
    from mcp_broker.watchdog import sample_process_group_cpu_percent

    assert sample_process_group_cpu_percent(os.getpgrp()) >= 0.0


def test_upstream_watchdog_samples_process_group_memory_mb() -> None:
    from mcp_broker.watchdog import sample_process_group_memory_mb

    result = subprocess.CompletedProcess(
        args=["ps"],
        returncode=0,
        stdout=" 1024\n 2048\n",
        stderr="",
    )

    assert sample_process_group_memory_mb(12345, runner=lambda _command: result) == 3.0


def test_upstream_watchdog_memory_sampler_handles_missing_process_group() -> None:
    from mcp_broker.watchdog import sample_process_group_memory_mb

    result = subprocess.CompletedProcess(
        args=["ps"],
        returncode=1,
        stdout="",
        stderr="",
    )

    assert sample_process_group_memory_mb(12345, runner=lambda _command: result) is None


def test_upstream_watchdog_memory_sampler_runs_ps_for_real_process_group() -> None:
    from mcp_broker.watchdog import sample_process_group_memory_mb

    assert sample_process_group_memory_mb(os.getpgrp()) is not None


def _build_sleeping_supervisor(
    tmp_path: Path,
    *,
    name: str,
    resources: object,
):
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.upstream_process import UpstreamProcessSupervisor

    worker = tmp_path / f"{name}.py"
    ready_file = tmp_path / f"{name}-ready.txt"
    worker.write_text(
        """
import sys
import time
from pathlib import Path

Path(sys.argv[1]).write_text("ready", encoding="utf-8")
while True:
    time.sleep(0.05)
""".strip(),
        encoding="utf-8",
    )
    supervisor = UpstreamProcessSupervisor(
        upstream=UpstreamConfig(
            name=name,
            command=sys.executable,
            args=[str(worker), str(ready_file)],
            mode="shared",
            enabled=True,
            state_dir=f"upstreams/{name}",
            tool_prefix=name,
            resources=resources,
        ),
        runtime_state_dir=tmp_path / "runtime" / "state",
    )
    return supervisor


def _read_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _start_sleeping_supervisor(
    tmp_path: Path,
    *,
    name: str,
    resources: object,
):
    supervisor = _build_sleeping_supervisor(tmp_path, name=name, resources=resources)
    ready_file = tmp_path / f"{name}-ready.txt"
    supervisor.start()
    deadline = time.monotonic() + 2
    while not ready_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    return supervisor
