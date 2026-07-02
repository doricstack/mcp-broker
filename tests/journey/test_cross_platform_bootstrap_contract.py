import json
import subprocess
import sys
from pathlib import Path

import pytest

from mcp_broker.service_templates import LAUNCHAGENT_LABEL, SYSTEMD_SERVICE_NAME, WINDOWS_TASK_NAME


pytestmark = pytest.mark.journey


def test_service_plan_cli_outputs_all_platform_plans_without_host_writes(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    home_dir = tmp_path / "home"
    target_paths = []

    for platform in ("macos", "linux", "windows"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mcp_broker.cli",
                "service",
                "plan",
                "--platform",
                platform,
                "--runtime-root",
                str(runtime_root),
                "--socket-path",
                str(runtime_root / "sockets" / "broker.sock"),
                "--config",
                str(runtime_root / "config" / "broker.yaml"),
                "--daemon-command",
                "mcp-broker-daemon",
                "--home-dir",
                str(home_dir),
            ],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        payload = json.loads(result.stdout)
        assert payload["platform"] == platform
        assert payload["dry_run"] is True
        assert payload["would_mutate"] is False
        assert payload["approval_required_for_apply"] is True
        assert payload["render_path"].startswith(str(runtime_root / "renders"))
        assert str(runtime_root) in payload["command"]
        assert str(runtime_root / "config" / "broker.yaml") in payload["command"]
        assert "navin" not in result.stdout.lower()
        target_paths.append(Path(payload["target_path"]))

    assert not (home_dir / "Library" / "LaunchAgents" / f"{LAUNCHAGENT_LABEL}.plist").exists()
    assert not (home_dir / ".config" / "systemd" / "user" / SYSTEMD_SERVICE_NAME).exists()
    assert not (runtime_root / "renders" / f"windows-task-{WINDOWS_TASK_NAME}.txt").exists()
    assert all(target_paths)
