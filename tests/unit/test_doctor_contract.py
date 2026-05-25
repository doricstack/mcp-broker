from pathlib import Path
import sys

import pytest


pytestmark = pytest.mark.unit


def test_doctor_finds_broken_enabled_stdio_commands(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig, UpstreamConfig
    from mcp_broker.doctor import find_broken_upstream_commands

    executable = tmp_path / "tool.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    missing = tmp_path / "missing-tool"
    disabled_missing = tmp_path / "disabled-missing-tool"
    http_url = "https://example.invalid/mcp"
    config = BrokerConfig(
        runtime=RuntimeConfig(
            root=tmp_path / "runtime",
            socket_path=tmp_path / "runtime" / "sockets" / "broker.sock",
            log_dir=tmp_path / "runtime" / "logs",
            state_dir=tmp_path / "runtime" / "state",
            secrets_dir=tmp_path / "runtime" / "secrets",
        ),
        broker=BrokerSettings(),
        upstreams={
            "path-good": UpstreamConfig(
                name="path-good",
                command=str(executable),
                transport="stdio",
            ),
            "path-missing": UpstreamConfig(
                name="path-missing",
                command=str(missing),
                transport="stdio",
            ),
            "path-disabled": UpstreamConfig(
                name="path-disabled",
                command=str(disabled_missing),
                mode="disabled",
                transport="stdio",
            ),
            "path-http": UpstreamConfig(
                name="path-http",
                command=http_url,
                transport="http",
            ),
            "path-python": UpstreamConfig(
                name="path-python",
                command=Path(sys.executable).name,
                transport="stdio",
            ),
        },
    )

    broken = find_broken_upstream_commands(config)

    assert [(item.upstream_name, item.command) for item in broken] == [
        ("path-missing", str(missing))
    ]


def test_doctor_main_reports_broken_upstream_commands(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from mcp_broker.doctor import main

    runtime_root = tmp_path / "runtime"
    missing = tmp_path / "missing-upstream-command"
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        f"""
runtime:
  root: {runtime_root}
  socket_path: {runtime_root}/sockets/broker.sock
  log_dir: {runtime_root}/logs
  state_dir: {runtime_root}/state
  secrets_dir: {runtime_root}/secrets
broker: {{}}
upstreams:
  broken:
    command: {missing}
    mode: shared
    transport: stdio
    tool_prefix: broken
""",
        encoding="utf-8",
    )

    result = main(["--config", str(config_path)])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert f"broken upstream command: broken: {missing}\n" == captured.err


def test_doctor_main_passes_when_commands_are_available(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from mcp_broker.doctor import main

    runtime_root = tmp_path / "runtime"
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        f"""
runtime:
  root: {runtime_root}
  socket_path: {runtime_root}/sockets/broker.sock
  log_dir: {runtime_root}/logs
  state_dir: {runtime_root}/state
  secrets_dir: {runtime_root}/secrets
broker: {{}}
upstreams:
  python:
    command: {sys.executable}
    mode: shared
    transport: stdio
    tool_prefix: python
""",
        encoding="utf-8",
    )

    result = main(["--config", str(config_path)])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == ""
    assert captured.err == ""
