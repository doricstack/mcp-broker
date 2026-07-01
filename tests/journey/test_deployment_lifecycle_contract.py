from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.support.bundles import write_signed_bundle
from tests.support.repo_paths import make_command, repo_root


pytestmark = pytest.mark.journey

ROOT = repo_root()


def test_deployment_stage_dry_run_validates_bundle_without_runtime_writes(tmp_path: Path) -> None:
    bundle_path = write_signed_bundle(tmp_path / "bundle.json")
    state_dir = tmp_path / "runtime" / "state"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mcp_broker.cli",
            "deployment",
            "stage",
            "--bundle",
            str(bundle_path),
            "--state-dir",
            str(state_dir),
            "--dry-run",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert "deployment dry-run:" in result.stdout
    assert str(bundle_path) in result.stdout
    assert not (state_dir / "deployments").exists()


def test_make_deployment_stage_dry_run_uses_state_dir_without_runtime_writes(tmp_path: Path) -> None:
    bundle_path = write_signed_bundle(tmp_path / "bundle.json")
    runtime_root = tmp_path / "runtime"

    result = subprocess.run(
        make_command(
            "deployment-stage",
            f"BUNDLE={bundle_path}",
            f"RUNTIME_ROOT={runtime_root}",
            "DEPLOYMENT_DRY_RUN=1",
        ),
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert "deployment dry-run:" in result.stdout
    assert str(bundle_path) in result.stdout
    assert not (runtime_root / "state" / "deployments").exists()
