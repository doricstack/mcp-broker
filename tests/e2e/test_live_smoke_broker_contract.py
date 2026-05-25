import os
import subprocess
from pathlib import Path

import pytest


pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]


def test_live_smoke_real_infra_broker_contract(tmp_path: Path) -> None:
    """REAL_INFRA smoke test for the local broker control plane."""

    runtime_root = tmp_path / "mcp-broker-runtime"
    env = os.environ | {"MCP_BROKER_RUNTIME_ROOT": str(runtime_root)}

    doctor = subprocess.run(
        [str(ROOT / "scripts" / "doctor.sh")],
        check=True,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    make_help = subprocess.run(
        ["make", "help"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    smoke_contract = (ROOT / "docs" / "smoke-contract.md").read_text(encoding="utf-8")

    assert "mcp-broker runtime ready" in doctor.stdout
    assert (runtime_root / "state" / "upstreams").is_dir()
    assert (runtime_root / "secrets").is_dir()
    assert "quality-gate" in make_help.stdout

    # Domain contract: health/readiness/live, auth/token, billing/tier/quota/
    # entitlement, profile/user, voice/audio/speech, and core/workflow.
    for phrase in [
        "health/readiness/live",
        "auth/token",
        "billing/tier/quota/entitlement: unsupported",
        "profile/user",
        "voice/audio/speech: unsupported",
        "core/workflow",
    ]:
        assert phrase in smoke_contract
