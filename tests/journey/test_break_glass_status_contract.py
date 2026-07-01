from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from tests.support.repo_paths import make_command, repo_root


pytestmark = pytest.mark.journey

ROOT = repo_root()
REASON = "Emergency policy bypass for deployment recovery"
OPERATOR = "operator@example.com"
EXPIRES_AT = "2099-07-01T12:30:00Z"


def test_break_glass_make_targets_create_audit_record_and_degraded_status(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime-root"

    create_result = _run_make(
        "break-glass-create",
        f"RUNTIME_ROOT={runtime_root}",
        f"BREAK_GLASS_REASON={REASON}",
        f"BREAK_GLASS_OPERATOR={OPERATOR}",
        f"BREAK_GLASS_EXPIRES_AT={EXPIRES_AT}",
        "BREAK_GLASS_BYPASS_POLICY_PATHS=policy.rollout.approval policy.bootstrap.apply",
    )
    created = _last_json(create_result.stdout)

    status_result = _run_make("break-glass-status", f"RUNTIME_ROOT={runtime_root}")
    status = _last_json(status_result.stdout)

    assert created["status"] == "active"
    assert created["audit_path"] == str(runtime_root / "state" / "break-glass" / "audit.jsonl")
    assert status["status"] == "active"
    assert status["degraded"] is True
    assert status["active_record"]["record_id"] == created["record_id"]
    assert (runtime_root / "state" / "break-glass" / "audit.jsonl").is_file()


def test_daemon_status_reports_degraded_while_break_glass_record_is_active(
    tmp_path: Path,
) -> None:
    from mcp_broker.break_glass import BreakGlassStore
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig
    from mcp_broker.config import BrokerIdentityConfig
    from mcp_broker.daemon import BrokerDaemon

    config = BrokerConfig(
        runtime=RuntimeConfig(
            root=tmp_path / "runtime",
            socket_path=tmp_path / "broker.sock",
            log_dir=tmp_path / "runtime" / "logs",
            state_dir=tmp_path / "runtime" / "state",
            secrets_dir=tmp_path / "runtime" / "secrets",
        ),
        broker=BrokerSettings(
            identity=BrokerIdentityConfig(
                broker_id="enterprise-broker",
                environment="local",
                bundle_version="2026.07.01",
            )
        ),
        upstreams={},
        profiles={},
    )
    BreakGlassStore(config.runtime.state_dir).create(
        reason=REASON,
        operator=OPERATOR,
        expires_at=EXPIRES_AT,
        bypassed_policy_paths=["policy.rollout.approval"],
        created_at="2026-07-01T12:00:00Z",
    )
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    daemon._started_at = "2026-07-01T11:59:59+00:00"

    daemon._write_status_snapshot("running")

    snapshot = json.loads(daemon.status_snapshot_path.read_text(encoding="utf-8"))
    assert snapshot["status"] == "degraded"
    assert snapshot["break_glass"]["degraded"] is True
    assert snapshot["break_glass"]["active_record"]["operator"] == OPERATOR
    assert snapshot["break_glass"]["active_record"]["bypassed_policy_paths"] == [
        "policy.rollout.approval"
    ]


def _run_make(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        make_command(*args),
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _last_json(output: str) -> dict[str, object]:
    for line in reversed(output.splitlines()):
        if line.startswith("{") and line.endswith("}"):
            loaded = json.loads(line)
            assert isinstance(loaded, dict)
            return loaded
    raise AssertionError(f"no JSON object in output: {output}")
