import json
import subprocess
from pathlib import Path

import pytest
import yaml


pytestmark = pytest.mark.live

ROOT = Path(__file__).resolve().parents[2]


def test_make_config_render_apply_preserves_copied_client_settings_and_rolls_back(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    codex_config = tmp_path / "copied-codex.toml"
    claude_config = tmp_path / "copied-claude.json"
    codex_original = (
        'approval_policy = "never"\n'
        "\n"
        "[profiles.dev]\n"
        'sandbox_mode = "danger-full-access"\n'
        "\n"
        '[mcp_servers."read-store"]\n'
        'command = "read-store"\n'
        'args = ["--scope", "project"]\n'
        "\n"
        '[mcp_servers."remote-repo"]\n'
        'command = "remote-repo"\n'
    )
    claude_original = {
        "theme": "dark",
        "permissions": {"allow": ["Bash(make test-live)"]},
        "mcpServers": {
            "read-store": {"command": "read-store"},
            "remote-repo": {"command": "remote-repo"},
        },
    }
    codex_config.write_text(codex_original, encoding="utf-8")
    claude_config.write_text(json.dumps(claude_original, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    broker_config = tmp_path / "broker.yaml"
    broker_config.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "codex": {
                        "format": "codex-toml",
                        "config_path": str(codex_config),
                        "entry_name": "mcp-broker",
                        "command": str(ROOT / "venv-mcp-broker" / "bin" / "mcp-broker-client"),
                    },
                    "claude": {
                        "format": "claude-json",
                        "config_path": str(claude_config),
                        "entry_name": "mcp-broker",
                        "command": str(ROOT / "venv-mcp-broker" / "bin" / "mcp-broker-client"),
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    _make("config-render", "CLIENT=codex", "CONFIG_RENDER_APPLY=1", f"CONFIG_PATH={broker_config}", f"RUNTIME_ROOT={runtime_root}")
    _make("config-render", "CLIENT=claude", "CONFIG_RENDER_APPLY=1", f"CONFIG_PATH={broker_config}", f"RUNTIME_ROOT={runtime_root}")

    codex_rendered = codex_config.read_text(encoding="utf-8")
    assert "[profiles.dev]" in codex_rendered
    assert 'approval_policy = "never"' in codex_rendered
    assert 'sandbox_mode = "danger-full-access"' in codex_rendered
    assert '[mcp_servers."mcp-broker"]' in codex_rendered
    assert '[mcp_servers."read-store"]' not in codex_rendered
    assert '[mcp_servers."remote-repo"]' not in codex_rendered
    assert (runtime_root / "renders" / "codex.config.toml").is_file()
    assert [path.read_text(encoding="utf-8") for path in (runtime_root / "backups" / "codex").glob("*.copied-codex.toml")] == [
        codex_original
    ]

    claude_rendered = json.loads(claude_config.read_text(encoding="utf-8"))
    assert claude_rendered["theme"] == "dark"
    assert claude_rendered["permissions"] == {"allow": ["Bash(make test-live)"]}
    assert set(claude_rendered["mcpServers"]) == {"mcp-broker"}
    assert claude_rendered["mcpServers"]["mcp-broker"]["command"] == str(
        ROOT / "venv-mcp-broker" / "bin" / "mcp-broker-client"
    )
    assert (runtime_root / "renders" / "claude.config.json").is_file()
    assert [
        json.loads(path.read_text(encoding="utf-8"))
        for path in (runtime_root / "backups" / "claude").glob("*.copied-claude.json")
    ] == [claude_original]

    _make("config-rollback", "CLIENT=codex", f"CONFIG_PATH={broker_config}", f"RUNTIME_ROOT={runtime_root}")
    _make("config-rollback", "CLIENT=claude", f"CONFIG_PATH={broker_config}", f"RUNTIME_ROOT={runtime_root}")

    assert codex_config.read_text(encoding="utf-8") == codex_original
    assert json.loads(claude_config.read_text(encoding="utf-8")) == claude_original


def test_make_config_render_apply_can_target_override_config_path(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    configured_config = tmp_path / "configured-client.toml"
    override_config = tmp_path / "generated" / "project-client.toml"
    configured_config.write_text("configured = true\n", encoding="utf-8")
    override_config.parent.mkdir()
    override_config.write_text(
        'project = true\n[mcp_servers."old-upstream"]\ncommand = "old-upstream"\n',
        encoding="utf-8",
    )
    broker_config = tmp_path / "broker.yaml"
    broker_config.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "toml-client": {
                        "format": "codex-toml",
                        "config_path": str(configured_config),
                        "entry_name": "mcp-broker",
                        "command": str(ROOT / "venv-mcp-broker" / "bin" / "mcp-broker-client"),
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    _make(
        "config-render",
        "CLIENT=toml-client",
        "CONFIG_RENDER_APPLY=1",
        f"CONFIG_RENDER_TARGET_PATH={override_config}",
        f"CONFIG_PATH={broker_config}",
        f"RUNTIME_ROOT={runtime_root}",
    )

    assert configured_config.read_text(encoding="utf-8") == "configured = true\n"
    assert override_config.read_text(encoding="utf-8") == (
        "project = true\n\n"
        '[mcp_servers."mcp-broker"]\n'
        f'command = "{ROOT}/venv-mcp-broker/bin/mcp-broker-client"\n'
        f'args = ["--socket-path", "{runtime_root}/sockets/broker.sock"]\n'
    )
    assert [
        path.read_text(encoding="utf-8")
        for path in (runtime_root / "backups" / "toml-client").glob("*.project-client.toml")
    ] == ['project = true\n[mcp_servers."old-upstream"]\ncommand = "old-upstream"\n']


def test_make_config_backup_copies_codex_and_claude_related_files_without_rendering(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    codex_config = tmp_path / "codex.toml"
    claude_config = tmp_path / "claude.json"
    claude_settings = tmp_path / "claude-settings.json"
    codex_config.write_text('approval_policy = "never"\n', encoding="utf-8")
    claude_config.write_text('{"mcpServers":{"read-store":{"command":"read-store"}}}\n', encoding="utf-8")
    claude_settings.write_text('{"theme":"dark"}\n', encoding="utf-8")
    broker_config = tmp_path / "broker.yaml"
    broker_config.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                },
                "clients": {
                    "codex": {
                        "format": "codex-toml",
                        "config_path": str(codex_config),
                        "entry_name": "mcp-broker",
                        "command": str(ROOT / "venv-mcp-broker" / "bin" / "mcp-broker-client"),
                    },
                    "claude": {
                        "format": "claude-json",
                        "config_path": str(claude_config),
                        "backup_paths": [str(claude_settings)],
                        "entry_name": "mcp-broker",
                        "command": str(ROOT / "venv-mcp-broker" / "bin" / "mcp-broker-client"),
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    codex = _make(
        "config-backup",
        "CLIENT=codex",
        "CONFIG_BACKUP_LABEL=prewire",
        f"CONFIG_PATH={broker_config}",
        f"RUNTIME_ROOT={runtime_root}",
    )
    claude = _make(
        "config-backup",
        "CLIENT=claude",
        "CONFIG_BACKUP_LABEL=prewire",
        f"CONFIG_PATH={broker_config}",
        f"RUNTIME_ROOT={runtime_root}",
    )

    assert "backup_paths" in codex.stdout
    assert "backup_paths" in claude.stdout
    assert (runtime_root / "backups" / "codex" / "prewire.codex.toml").read_text(
        encoding="utf-8"
    ) == 'approval_policy = "never"\n'
    assert (runtime_root / "backups" / "claude" / "prewire.claude.json").read_text(
        encoding="utf-8"
    ) == '{"mcpServers":{"read-store":{"command":"read-store"}}}\n'
    assert (runtime_root / "backups" / "claude" / "prewire.claude-settings.json").read_text(
        encoding="utf-8"
    ) == '{"theme":"dark"}\n'
    assert not (runtime_root / "renders" / "codex.config.toml").exists()
    assert not (runtime_root / "renders" / "claude.config.json").exists()


def test_upgrade_render_and_rollback_preserve_runtime_state(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    client_config = tmp_path / "client.toml"
    client_name = "test-client"
    original_config = 'approval_policy = "on-request"\n'
    client_config.write_text(original_config, encoding="utf-8")
    broker_config = tmp_path / "broker.yaml"
    broker_config.write_text(
        yaml.safe_dump(
            {
                "runtime": {
                    "root": str(runtime_root),
                    "socket_path": str(runtime_root / "sockets" / "broker.sock"),
                    "log_dir": str(runtime_root / "logs"),
                    "state_dir": str(runtime_root / "state"),
                    "secrets_dir": str(runtime_root / "secrets"),
                },
                "clients": {
                    client_name: {
                        "format": "codex-toml",
                        "config_path": str(client_config),
                        "entry_name": "mcp-broker",
                        "command": str(ROOT / "venv-mcp-broker" / "bin" / "mcp-broker-client"),
                    },
                },
                "upstreams": {},
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    preserved_files = {
        runtime_root / "secrets" / "TOKEN_NAME": "secret-value\n",
        runtime_root / "state" / "upstreams" / "example" / "state.json": '{"ok": true}\n',
        runtime_root / "backups" / "manual" / "keep.txt": "manual backup\n",
        runtime_root / "renders" / "operator-note.txt": "reviewed render\n",
    }
    for path, content in preserved_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    _make(
        "config-render",
        f"CLIENT={client_name}",
        "CONFIG_RENDER_APPLY=1",
        f"CONFIG_PATH={broker_config}",
        f"RUNTIME_ROOT={runtime_root}",
    )
    first_render = client_config.read_text(encoding="utf-8")
    _make(
        "config-render",
        f"CLIENT={client_name}",
        "CONFIG_RENDER_APPLY=1",
        f"CONFIG_PATH={broker_config}",
        f"RUNTIME_ROOT={runtime_root}",
    )
    _make(
        "config-rollback",
        f"CLIENT={client_name}",
        f"CONFIG_PATH={broker_config}",
        f"RUNTIME_ROOT={runtime_root}",
    )

    assert client_config.read_text(encoding="utf-8") == first_render
    for path, content in preserved_files.items():
        assert path.read_text(encoding="utf-8") == content


def _make(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
