"""Process-group watchdog helpers."""

from __future__ import annotations

import subprocess
from typing import Callable


ProcessRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def sample_process_group_cpu_percent(
    pgid: int,
    *,
    runner: ProcessRunner | None = None,
) -> float:
    command = ["ps", "-o", "pcpu=", "-g", str(pgid)]
    result = (runner or _run_ps)(command)
    if result.returncode != 0:
        return 0.0
    return sum(float(line.strip()) for line in result.stdout.splitlines() if line.strip())


def sample_process_group_memory_mb(
    pgid: int,
    *,
    runner: ProcessRunner | None = None,
) -> float | None:
    command = ["ps", "-o", "rss=", "-g", str(pgid)]
    result = (runner or _run_ps)(command)
    if result.returncode != 0:
        return None
    rss_kb = sum(float(line.strip()) for line in result.stdout.splitlines() if line.strip())
    return rss_kb / 1024


def _run_ps(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
    )
