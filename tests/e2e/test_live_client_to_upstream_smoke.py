import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_MCP_SERVER = ROOT / "tests" / "support" / "sample_mcp_server.py"


def test_client_shim_calls_stdio_upstream_through_broker_socket(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.daemon import BrokerDaemon

    config_path = _broker_config(tmp_path)
    config = BrokerConfig.from_file(config_path)
    daemon = BrokerDaemon(
        runtime_root=config.runtime.root,
        socket_path=config.runtime.socket_path,
        broker_config=config,
    )
    request = {
        "jsonrpc": "2.0",
        "id": "call-1",
        "method": "tools/call",
        "params": {
            "name": "sample.echo",
            "arguments": {"message": "hello from shim"},
        },
    }

    daemon.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "mcp_broker.client",
                "--socket-path",
                str(config.runtime.socket_path),
                "--profile",
                "manual-test",
            ],
            cwd=ROOT,
            input=(json.dumps(request) + "\n").encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    finally:
        daemon.stop()
        daemon.join(timeout=5)

    assert result.stderr == b""
    assert json.loads(result.stdout.decode("utf-8")) == {
        "jsonrpc": "2.0",
        "id": "call-1",
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": "hello from shim",
                }
            ]
        },
    }
    assert (config.runtime.state_dir / "upstreams" / "sample" / "requests.log").is_file()


def _broker_config(tmp_path: Path) -> Path:
    runtime_root = tmp_path / "runtime"
    path = tmp_path / "broker.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(_socket_path(tmp_path)),
                    "state_dir": str(runtime_root / "state"),
                },
                "broker": {"tool_namespace_separator": "."},
                "profiles": {
                    "manual-test": {
                        "max_tools": 200,
                        "compact_tools_enabled": False,
                    }
                },
                "upstreams": {
                    "sample": {
                        "command": sys.executable,
                        "args": [str(SAMPLE_MCP_SERVER)],
                        "mode": "shared",
                        "transport": "stdio",
                        "tool_prefix": "sample",
                        "state_dir": "upstreams/sample",
                        "profiles": ["manual-test"],
                    }
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def _socket_path(tmp_path: Path) -> Path:
    return Path("/tmp") / f"mcp-broker-smoke-{os.getpid()}-{tmp_path.name}.sock"
