import os
import subprocess
from pathlib import Path
import sys

import pytest


pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]


def test_doctor_script_creates_runtime_layout(tmp_path: Path) -> None:
    runtime_root = tmp_path / "mcp-broker-runtime"
    env = os.environ | {"MCP_BROKER_RUNTIME_ROOT": str(runtime_root)}

    result = subprocess.run(
        [str(ROOT / "scripts" / "doctor.sh")],
        check=True,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert "mcp-broker runtime ready" in result.stdout
    for relative in [
        "logs",
        "run",
        "secrets",
        "sockets",
        "state/upstreams",
    ]:
        assert (runtime_root / relative).is_dir()


def test_make_doctor_fails_for_enabled_upstream_with_missing_command(tmp_path: Path) -> None:
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
  good:
    command: {sys.executable}
    mode: shared
    transport: stdio
    tool_prefix: good
  broken:
    command: {tmp_path}/missing-upstream-command
    mode: shared
    transport: stdio
    tool_prefix: broken
  disabled-broken:
    command: {tmp_path}/disabled-missing-command
    mode: disabled
    transport: stdio
    tool_prefix: disabled-broken
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "make",
            "-C",
            str(ROOT),
            "doctor",
            f"CONFIG_PATH={config_path}",
            f"RUNTIME_ROOT={runtime_root}",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    output = result.stdout + result.stderr

    assert result.returncode != 0
    assert "broken upstream command: broken" in output
    assert str(tmp_path / "missing-upstream-command") in output
    assert "disabled-broken" not in output
