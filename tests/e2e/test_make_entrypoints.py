import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]


def test_make_help_exposes_broker_entrypoints() -> None:
    result = subprocess.run(
        ["make", "help"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    for target in [
        "setup",
        "test",
        "test-unit",
        "test-journey",
        "test-live",
        "test-e2e",
        "broker-start",
        "broker-stop",
        "broker-status",
        "broker-reap",
        "broker-smoke",
        "tools-count",
        "facade-smoke",
        "codex-facade-smoke",
        "claude-facade-smoke",
        "gemini-facade-smoke",
        "discovery-parity",
        "codex-claude-discovery-parity",
        "launchagent-install",
        "launchagent-load",
        "launchagent-uninstall",
        "launchagent-unload",
        "systemd-install",
        "systemd-load",
        "systemd-uninstall",
        "systemd-unload",
        "windows-install",
        "windows-load",
        "windows-uninstall",
        "windows-unload",
        "linux-container-smoke",
        "windows-powershell-smoke",
        "release-smoke",
        "config-init",
        "config-backup",
        "codex-app-policy",
        "config-render",
        "config-rollback",
        "precommit",
        "quality-gate",
    ]:
        assert target in result.stdout

    for maintainer_only_target in [
        "violations",
        "grade-quality",
        "maintainer-violations",
        "maintainer-grade-quality",
        "maintainer-precommit",
        "maintainer-quality-gate",
    ]:
        assert maintainer_only_target not in result.stdout
