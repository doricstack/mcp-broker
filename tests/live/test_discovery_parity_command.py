import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

from tests.support.json_report import report_from_stdout


pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]


def test_discovery_parity_report_parser_ignores_make_directory_noise() -> None:
    report = report_from_stdout(
        "\n".join(
            [
                "make[1]: Entering directory '/tmp/repo'",
                '{"matches": true, "mismatches": []}',
                "make[1]: Leaving directory '/tmp/repo'",
            ]
        ),
        label="discovery parity",
    )

    assert report == {"matches": True, "mismatches": []}


def test_make_discovery_parity_compares_profiles_through_client_shim(
    tmp_path: Path,
) -> None:
    from mcp_broker.discovery_parity import main as discovery_parity_main

    runtime_root = tmp_path / "runtime"
    socket_path = Path("/tmp") / f"mcp-broker-discovery-parity-{uuid.uuid4().hex}.sock"
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(socket_path),
                },
                "profiles": {
                    "codex": {
                        "max_tools": 80,
                        "compact_tools_enabled": True,
                    },
                    "claude": {
                        "max_tools": 80,
                        "compact_tools_enabled": True,
                    },
                },
                "upstreams": {
                    "fake": {
                        "enabled": True,
                        "mode": "shared",
                        "transport": "stdio",
                        "purpose": "Fake upstream for discovery parity.",
                        "tags": ["fake", "parity"],
                        "tool_prefix": "fake",
                        "command": sys.executable,
                        "args": [str(_parity_worker(tmp_path))],
                        "state_dir": "upstreams/fake",
                        "profiles": ["codex", "claude"],
                    }
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "make",
            "discovery-parity",
            f"CONFIG_PATH={config_path}",
            f"RUNTIME_ROOT={runtime_root}",
            f"SOCKET_PATH={socket_path}",
            "PARITY_LEFT_PROFILE=codex",
            "PARITY_RIGHT_PROFILE=claude",
            "DISCOVERY_QUERY=echo",
            "DISCOVERY_CALL_TOOL=fake.echo",
            'DISCOVERY_CALL_ARGS={"message":"hello"}',
        ],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    report = report_from_stdout(result.stdout, label="discovery parity")

    assert (
        discovery_parity_main(
            [
                "--config",
                str(config_path),
                "--left-profile",
                "codex",
                "--right-profile",
                "claude",
                "--query",
                "echo",
                "--call-tool",
                "fake.echo",
                "--call-args",
                '{"message":"hello"}',
            ]
        )
        == 0
    )

    assert report["matches"] is True
    assert report["mismatches"] == []
    assert report["profiles"]["codex"]["visible_upstreams"] == ["fake"]
    assert report["profiles"]["claude"]["visible_upstreams"] == ["fake"]
    assert report["profiles"]["codex"]["search_matches"] == ["fake.echo"]
    assert report["profiles"]["claude"]["search_matches"] == ["fake.echo"]
    assert not (runtime_root / "run" / "upstreams" / "fake.json").exists()


def _parity_worker(tmp_path: Path) -> Path:
    path = tmp_path / "parity_worker.py"
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
            "serverInfo": {"name": "fake", "version": "0.0.1"},
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
