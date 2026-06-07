from pathlib import Path
import sys

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def test_doctor_main_help_documents_runtime_config(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.doctor import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert "\nValidate mcp-broker runtime config\n" in captured.out
    assert "XXValidate" not in captured.out
    assert "--config" in captured.out


def test_doctor_main_requires_config_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.doctor import main

    with pytest.raises(SystemExit) as exc:
        main([])

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "the following arguments are required: --config" in captured.err


def test_doctor_command_available_expands_user_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.doctor import _command_available

    home = tmp_path / "home"
    home.mkdir()
    executable = home / "tool.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))

    assert _command_available("~/tool.sh") is True


def test_doctor_command_available_uses_path_lookup_for_bare_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.doctor as doctor

    monkeypatch.setattr(
        doctor.shutil,
        "which",
        lambda command: "/usr/local/bin/tool" if command == "tool" else None,
    )

    assert doctor._command_available("tool") is True
    assert doctor._command_available("missing-tool") is False


def test_doctor_command_available_rejects_non_executable_file(tmp_path: Path) -> None:
    from mcp_broker.doctor import _command_available

    script = tmp_path / "tool.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o644)

    assert _command_available(str(script)) is False


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
                command=sys.executable,
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
