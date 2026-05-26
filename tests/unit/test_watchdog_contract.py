from __future__ import annotations

import subprocess

import pytest

from mcp_broker import watchdog


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def test_watchdog_cpu_sampler_uses_process_group_cpu_command() -> None:
    seen_commands: list[list[str]] = []

    def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        seen_commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="1.0\n 2.5\n\n")

    assert watchdog.sample_process_group_cpu_percent(12345, runner=runner) == 3.5
    assert seen_commands == [["ps", "-o", "pcpu=", "-g", "12345"]]


def test_watchdog_run_ps_captures_text_without_checking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0, stdout="0.0\n")

    monkeypatch.setattr(watchdog.subprocess, "run", fake_run)

    result = watchdog._run_ps(["ps", "-o", "pcpu=", "-g", "12345"])

    assert result.stdout == "0.0\n"
    assert calls == [
        (
            (["ps", "-o", "pcpu=", "-g", "12345"],),
            {"capture_output": True, "check": False, "text": True},
        )
    ]
