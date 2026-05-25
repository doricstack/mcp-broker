import json
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.journey


def test_codex_render_dry_run_replaces_many_servers_with_broker_entry(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    broker_config_path = _broker_config(tmp_path)
    target_path = tmp_path / "codex.toml"
    target_path.write_text(
        "\n".join(
            [
                '[mcp_servers."read-store"]',
                'command = "read-store"',
                '[mcp_servers."remote-repo"]',
                'command = "remote-repo"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = render_client_config(
        BrokerConfig.from_file(broker_config_path),
        client_name="codex",
        dry_run=True,
    )

    assert target_path.read_text(encoding="utf-8") == (
        '[mcp_servers."read-store"]\n'
        'command = "read-store"\n'
        '[mcp_servers."remote-repo"]\n'
        'command = "remote-repo"\n'
    )
    assert result.target_path == target_path
    assert result.rendered_path == tmp_path / "runtime" / "renders" / "codex.config.toml"
    rendered = result.rendered_path.read_text(encoding="utf-8")
    assert '[mcp_servers."mcp-broker"]' in rendered
    assert 'command = "/repo/venv-mcp-broker/bin/mcp-broker-client"' in rendered
    assert 'args = ["--socket-path", "' + str(tmp_path / "runtime" / "sockets" / "broker.sock") + '"]' in rendered
    assert '[mcp_servers."read-store"]' not in rendered
    assert '[mcp_servers."remote-repo"]' not in rendered


def test_claude_render_dry_run_replaces_many_servers_with_broker_entry(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config

    broker_config_path = _broker_config(tmp_path)
    target_path = tmp_path / "claude.json"
    target_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "read-store": {"command": "read-store"},
                    "remote-repo": {"command": "remote-repo"},
                }
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    result = render_client_config(
        BrokerConfig.from_file(broker_config_path),
        client_name="claude",
        dry_run=True,
    )

    assert json.loads(target_path.read_text(encoding="utf-8")) == {
        "mcpServers": {
            "read-store": {"command": "read-store"},
            "remote-repo": {"command": "remote-repo"},
        }
    }
    assert result.rendered_path == tmp_path / "runtime" / "renders" / "claude.config.json"
    rendered = json.loads(result.rendered_path.read_text(encoding="utf-8"))
    assert rendered == {
        "mcpServers": {
            "mcp-broker": {
                "command": "/repo/venv-mcp-broker/bin/mcp-broker-client",
                "args": ["--socket-path", str(tmp_path / "runtime" / "sockets" / "broker.sock")],
            }
        }
    }


def test_apply_render_creates_backup_and_rollback_restores_previous_config(tmp_path: Path) -> None:
    from mcp_broker.config import BrokerConfig
    from mcp_broker.config_render import render_client_config, rollback_client_config

    broker_config_path = _broker_config(tmp_path)
    target_path = tmp_path / "claude.json"
    original_config = {"mcpServers": {"read-store": {"command": "read-store"}}}
    target_path.write_text(json.dumps(original_config, sort_keys=True), encoding="utf-8")

    result = render_client_config(
        BrokerConfig.from_file(broker_config_path),
        client_name="claude",
        dry_run=False,
        backup_label="20260524T000000Z",
    )

    assert result.backup_path == tmp_path / "runtime" / "backups" / "claude" / "20260524T000000Z.claude.json"
    assert json.loads(result.backup_path.read_text(encoding="utf-8")) == original_config
    assert json.loads(target_path.read_text(encoding="utf-8")) == {
        "mcpServers": {
            "mcp-broker": {
                "command": "/repo/venv-mcp-broker/bin/mcp-broker-client",
                "args": ["--socket-path", str(tmp_path / "runtime" / "sockets" / "broker.sock")],
            }
        }
    }

    rollback = rollback_client_config(BrokerConfig.from_file(broker_config_path), client_name="claude")

    assert rollback.restored_path == result.backup_path
    assert json.loads(target_path.read_text(encoding="utf-8")) == original_config


def _broker_config(tmp_path: Path) -> Path:
    path = tmp_path / "broker.yaml"
    target_codex = tmp_path / "codex.toml"
    target_claude = tmp_path / "claude.json"
    runtime_root = tmp_path / "runtime"
    path.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "codex": {
                        "format": "codex-toml",
                        "config_path": str(target_codex),
                        "entry_name": "mcp-broker",
                        "command": "/repo/venv-mcp-broker/bin/mcp-broker-client",
                    },
                    "claude": {
                        "format": "claude-json",
                        "config_path": str(target_claude),
                        "entry_name": "mcp-broker",
                        "command": "/repo/venv-mcp-broker/bin/mcp-broker-client",
                    },
                },
                "upstreams": {
                    "read-store": {
                        "command": "read-store",
                        "profiles": ["codex", "claude"],
                    }
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path
