import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

from tests.support.json_report import report_from_stdout


pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]


def test_make_profile_validation_uses_yaml_configured_smoke_probes(
    tmp_path: Path,
) -> None:
    from mcp_broker.profile_validation import main as profile_validation_main

    runtime_root = tmp_path / "runtime"
    socket_path = Path("/tmp") / f"mcp-broker-profile-validation-{uuid.uuid4().hex}.sock"
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(_profile_validation_config(tmp_path, runtime_root, socket_path), sort_keys=True),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "make",
            "profile-validation",
            f"CONFIG_PATH={config_path}",
            f"RUNTIME_ROOT={runtime_root}",
            f"SOCKET_PATH={socket_path}",
            "PROFILE=llm",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    report = report_from_stdout(result.stdout, label="profile validation")

    assert report["matches"] is True
    assert report["profile"] == "llm"
    assert report["missing_probes"] == []
    assert report["validated_upstreams"] == ["echo"]
    assert report["probe_results"]["echo"]["call_output_bytes"] == len('{"message": "hello"}')
    assert "call_text" not in report["probe_results"]["echo"]
    assert not (runtime_root / "run" / "upstreams" / "echo.json").exists()

    assert profile_validation_main(["--config", str(config_path), "--profile", "llm"]) == 0


def _profile_validation_config(
    tmp_path: Path, runtime_root: Path, socket_path: Path
) -> dict:
    return {
        "runtime": {"root": str(runtime_root), "socket_path": str(socket_path)},
        "profiles": {"llm": {"max_tools": 80, "compact_tools_enabled": True}},
        "upstreams": {
            "echo": {
                "enabled": True,
                "mode": "shared",
                "transport": "stdio",
                "purpose": "Echo upstream for profile validation.",
                "tags": ["echo", "validation"],
                "tool_prefix": "echo",
                "command": sys.executable,
                "args": [str(_validation_worker(tmp_path))],
                "state_dir": "upstreams/echo",
                "profiles": ["llm"],
                "smoke": {
                    "query": "echo",
                    "tool": "echo.echo",
                    "arguments": {"message": "hello"},
                },
            }
        },
    }


def _validation_worker(tmp_path: Path) -> Path:
    path = tmp_path / "validation_worker.py"
    path.write_text(
        """
import json
import sys


for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        result = {
            "protocolVersion": request.get("params", {}).get("protocolVersion", "2025-11-25"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "echo", "version": "0.0.1"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo a provided message.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                    },
                }
            ]
        }
    else:
        text = json.dumps(request.get("params", {}).get("arguments", {}), sort_keys=True)
        result = {"content": [{"type": "text", "text": text}]}
    print(json.dumps({"jsonrpc": "2.0", "id": request.get("id"), "result": result}), flush=True)
""".strip(),
        encoding="utf-8",
    )
    return path
