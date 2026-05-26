import subprocess
from pathlib import Path

import pytest
import yaml

from tests.support.repo_paths import make_command

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]


def test_make_config_render_dry_run_does_not_write_user_config(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    user_config = tmp_path / "codex.toml"
    user_config.write_text('[mcp_servers."read-store"]\ncommand = "read-store"\n', encoding="utf-8")
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "codex": {
                        "format": "codex-toml",
                        "config_path": str(user_config),
                        "entry_name": "mcp-broker",
                        "command": str(ROOT / "venv-mcp-broker" / "bin" / "mcp-broker-client"),
                    }
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        make_command(
            "config-render",
            "CLIENT=codex",
            f"CONFIG_PATH={config_path}",
            f"RUNTIME_ROOT={runtime_root}",
        ),
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    rendered_path = runtime_root / "renders" / "codex.config.toml"
    assert "dry_run" in result.stdout
    assert rendered_path.is_file()
    assert '[mcp_servers."mcp-broker"]' in rendered_path.read_text(encoding="utf-8")
    assert user_config.read_text(encoding="utf-8") == '[mcp_servers."read-store"]\ncommand = "read-store"\n'
