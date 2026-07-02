import json
from pathlib import Path

import pytest

from mcp_broker.service_templates import (
    LAUNCHAGENT_LABEL,
    SYSTEMD_SERVICE_NAME,
    WINDOWS_TASK_NAME,
    ServiceTemplateError,
    build_service_plan,
)


pytestmark = pytest.mark.unit


def test_macos_service_plan_is_dry_run_and_uses_runtime_state(tmp_path: Path) -> None:
    plan = build_service_plan(
        platform="macos",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "runtime" / "sockets" / "broker.sock",
        config_path=tmp_path / "runtime" / "config" / "broker.yaml",
        daemon_command="/opt/mcp-broker/bin/mcp-broker-daemon",
        home_dir=tmp_path / "home",
    )

    assert plan["platform"] == "macos"
    assert plan["service_manager"] == "launchd"
    assert plan["dry_run"] is True
    assert plan["would_mutate"] is False
    assert plan["approval_required_for_apply"] is True
    assert plan["target_path"] == str(
        tmp_path / "home" / "Library" / "LaunchAgents" / f"{LAUNCHAGENT_LABEL}.plist"
    )
    assert plan["render_path"] == str(tmp_path / "runtime" / "renders" / f"{LAUNCHAGENT_LABEL}.plist")
    assert plan["command"] == (
        "/opt/mcp-broker/bin/mcp-broker-daemon serve "
        f"--runtime-root {tmp_path / 'runtime'} "
        f"--socket-path {tmp_path / 'runtime' / 'sockets' / 'broker.sock'} "
        f"--config {tmp_path / 'runtime' / 'config' / 'broker.yaml'}"
    )
    assert plan["environment"]["MCP_BROKER_RUNTIME_ROOT"] == str(tmp_path / "runtime")
    assert "navin" not in json.dumps(plan).lower()


def test_linux_service_plan_targets_systemd_user_service(tmp_path: Path) -> None:
    plan = build_service_plan(
        platform="linux",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "runtime" / "sockets" / "broker.sock",
        config_path=tmp_path / "runtime" / "config" / "broker.yaml",
        daemon_command="mcp-broker-daemon",
        home_dir=tmp_path / "home",
    )

    assert plan["platform"] == "linux"
    assert plan["service_manager"] == "systemd-user"
    assert plan["target_path"] == str(
        tmp_path / "home" / ".config" / "systemd" / "user" / SYSTEMD_SERVICE_NAME
    )
    assert plan["render_path"] == str(tmp_path / "runtime" / "renders" / SYSTEMD_SERVICE_NAME)
    assert plan["load_command"] == f"systemctl --user enable --now {SYSTEMD_SERVICE_NAME}"
    assert plan["unload_command"] == f"systemctl --user disable --now {SYSTEMD_SERVICE_NAME}"
    assert plan["would_mutate"] is False


def test_windows_service_plan_targets_scheduled_task(tmp_path: Path) -> None:
    plan = build_service_plan(
        platform="windows",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "runtime" / "sockets" / "broker.sock",
        config_path=tmp_path / "runtime" / "config" / "broker.yaml",
        daemon_command="mcp-broker-daemon.exe",
        home_dir=tmp_path / "home",
    )

    assert plan["platform"] == "windows"
    assert plan["service_manager"] == "windows-scheduled-task"
    assert plan["target_path"] == rf"Task Scheduler\{WINDOWS_TASK_NAME}"
    assert plan["render_path"] == str(tmp_path / "runtime" / "renders" / f"windows-task-{WINDOWS_TASK_NAME}.txt")
    assert plan["load_command"] == f"Register-ScheduledTask -TaskName {WINDOWS_TASK_NAME}"
    assert plan["unload_command"] == f"Unregister-ScheduledTask -TaskName {WINDOWS_TASK_NAME} -Confirm:$false"
    assert plan["would_mutate"] is False


def test_service_plan_rejects_unknown_platform(tmp_path: Path) -> None:
    with pytest.raises(ServiceTemplateError, match="unsupported service platform"):
        build_service_plan(
            platform="solaris",
            runtime_root=tmp_path / "runtime",
            socket_path=tmp_path / "runtime" / "sockets" / "broker.sock",
            config_path=tmp_path / "runtime" / "config" / "broker.yaml",
            daemon_command="mcp-broker-daemon",
            home_dir=tmp_path / "home",
        )


def test_service_plan_rejects_empty_daemon_command(tmp_path: Path) -> None:
    with pytest.raises(ServiceTemplateError, match="daemon command is required"):
        build_service_plan(
            platform="linux",
            runtime_root=tmp_path / "runtime",
            socket_path=tmp_path / "runtime" / "sockets" / "broker.sock",
            config_path=tmp_path / "runtime" / "config" / "broker.yaml",
            daemon_command=" ",
            home_dir=tmp_path / "home",
        )
