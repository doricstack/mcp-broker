from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_active_runtime_launcher_builds_argv_from_active_manifest(tmp_path: Path) -> None:
    from mcp_broker.runtime_install import RuntimeInstallStore
    from mcp_broker.runtime_launcher import ActiveRuntimeLauncher

    state_dir = tmp_path / "runtime" / "state"
    runtime_path = tmp_path / "installed" / "versions" / "2.1.0"
    entrypoint = "bin/mcp-broker"
    runtime_path.mkdir(parents=True)
    (runtime_path / "bin").mkdir()
    (runtime_path / entrypoint).write_text("#!/bin/sh\n", encoding="utf-8")
    (runtime_path / entrypoint).chmod(0o755)

    installed = RuntimeInstallStore(state_dir).record_installed_runtime(
        version="2.1.0",
        runtime_path=runtime_path,
        entrypoint=entrypoint,
        artifact_digest="sha256:first-runtime",
    )

    launch_plan = ActiveRuntimeLauncher(state_dir).launch_plan(["status"])

    assert launch_plan == {
        "entrypoint": entrypoint,
        "manifest_path": installed["manifest_path"],
        "runtime_id": installed["runtime_id"],
        "runtime_path": str(runtime_path),
        "argv": [str(runtime_path / entrypoint), "status"],
    }


def test_active_runtime_launcher_fails_closed_without_active_manifest(tmp_path: Path) -> None:
    from mcp_broker.runtime_launcher import ActiveRuntimeLauncher, RuntimeLauncherError

    with pytest.raises(RuntimeLauncherError, match="active runtime"):
        ActiveRuntimeLauncher(tmp_path / "runtime" / "state").launch_plan(["status"])


def test_active_runtime_launcher_rejects_pointer_to_manifest_outside_install_root(
    tmp_path: Path,
) -> None:
    from mcp_broker.runtime_install import RuntimeInstallStore
    from mcp_broker.runtime_launcher import ActiveRuntimeLauncher, RuntimeLauncherError

    state_dir = tmp_path / "runtime" / "state"
    runtime_path = tmp_path / "installed" / "versions" / "2.1.0"
    entrypoint = "bin/mcp-broker"
    runtime_path.mkdir(parents=True)
    (runtime_path / "bin").mkdir()
    (runtime_path / entrypoint).write_text("#!/bin/sh\n", encoding="utf-8")
    (runtime_path / entrypoint).chmod(0o755)
    RuntimeInstallStore(state_dir).record_installed_runtime(
        version="2.1.0",
        runtime_path=runtime_path,
        entrypoint=entrypoint,
        artifact_digest="sha256:first-runtime",
    )
    external_manifest = tmp_path / "external-runtime-manifest.json"
    external_manifest.write_text(
        json.dumps(
            {
                "entrypoint": entrypoint,
                "runtime_id": "2.1.0-external",
                "runtime_path": str(runtime_path),
            }
        ),
        encoding="utf-8",
    )
    (state_dir / "runtime-install" / "active-runtime.json").write_text(
        json.dumps(
            {
                "runtime_id": "2.1.0-external",
                "manifest_path": str(external_manifest),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeLauncherError, match="manifest path"):
        ActiveRuntimeLauncher(state_dir).launch_plan(["status"])


def test_active_runtime_launcher_rejects_symlink_entrypoint_escape(tmp_path: Path) -> None:
    from mcp_broker.runtime_install import RuntimeInstallStore
    from mcp_broker.runtime_launcher import ActiveRuntimeLauncher, RuntimeLauncherError

    state_dir = tmp_path / "runtime" / "state"
    runtime_path = tmp_path / "installed" / "versions" / "2.1.0"
    outside_bin = tmp_path / "outside-bin"
    outside_bin.mkdir(parents=True)
    (outside_bin / "mcp-broker").write_text("#!/bin/sh\n", encoding="utf-8")
    (outside_bin / "mcp-broker").chmod(0o755)
    runtime_path.mkdir(parents=True)
    os.symlink(outside_bin, runtime_path / "bin")
    RuntimeInstallStore(state_dir).record_installed_runtime(
        version="2.1.0",
        runtime_path=runtime_path,
        entrypoint="bin/mcp-broker",
        artifact_digest="sha256:first-runtime",
    )

    with pytest.raises(RuntimeLauncherError, match="entrypoint must stay"):
        ActiveRuntimeLauncher(state_dir).launch_plan(["status"])


def test_active_runtime_launcher_reports_malformed_pointer(tmp_path: Path) -> None:
    from mcp_broker.runtime_launcher import ActiveRuntimeLauncher, RuntimeLauncherError

    pointer = tmp_path / "runtime" / "state" / "runtime-install" / "active-runtime.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"runtime_id": "2.1.0-missing-path"}), encoding="utf-8")

    with pytest.raises(RuntimeLauncherError, match="manifest_path"):
        ActiveRuntimeLauncher(tmp_path / "runtime" / "state").launch_plan(["status"])


def test_active_runtime_launcher_rejects_non_executable_entrypoint(tmp_path: Path) -> None:
    from mcp_broker.runtime_install import RuntimeInstallStore
    from mcp_broker.runtime_launcher import ActiveRuntimeLauncher, RuntimeLauncherError

    state_dir = tmp_path / "runtime" / "state"
    runtime_path = tmp_path / "installed" / "versions" / "2.1.0"
    entrypoint = "bin/mcp-broker"
    runtime_path.mkdir(parents=True)
    (runtime_path / "bin").mkdir()
    (runtime_path / entrypoint).write_text("#!/bin/sh\n", encoding="utf-8")
    RuntimeInstallStore(state_dir).record_installed_runtime(
        version="2.1.0",
        runtime_path=runtime_path,
        entrypoint=entrypoint,
        artifact_digest="sha256:first-runtime",
    )

    with pytest.raises(RuntimeLauncherError, match="not executable"):
        ActiveRuntimeLauncher(state_dir).launch_plan(["status"])


def test_runtime_launch_plan_cli_returns_controlled_error_for_invalid_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.cli import main

    pointer = tmp_path / "runtime" / "state" / "runtime-install" / "active-runtime.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"runtime_id": "2.1.0-missing-path"}), encoding="utf-8")

    assert main(["runtime", "launch-plan", "--state-dir", str(tmp_path / "runtime" / "state")]) == 1

    captured = capsys.readouterr()
    assert "manifest_path" in captured.err
    assert captured.out == ""


def test_runtime_launch_plan_cli_uses_public_entrypoint(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.cli import main
    from mcp_broker.runtime_install import RuntimeInstallStore

    state_dir = tmp_path / "runtime" / "state"
    runtime_path = tmp_path / "installed" / "versions" / "2.1.0"
    entrypoint = "bin/mcp-broker"
    runtime_path.mkdir(parents=True)
    (runtime_path / "bin").mkdir()
    (runtime_path / entrypoint).write_text("#!/bin/sh\n", encoding="utf-8")
    (runtime_path / entrypoint).chmod(0o755)
    installed = RuntimeInstallStore(state_dir).record_installed_runtime(
        version="2.1.0",
        runtime_path=runtime_path,
        entrypoint=entrypoint,
        artifact_digest="sha256:first-runtime",
    )

    assert main(["runtime", "launch-plan", "--state-dir", str(state_dir), "--", "status"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "entrypoint": entrypoint,
        "manifest_path": installed["manifest_path"],
        "runtime_id": installed["runtime_id"],
        "runtime_path": str(runtime_path),
        "argv": [str(runtime_path / entrypoint), "status"],
    }
