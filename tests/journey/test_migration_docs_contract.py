from pathlib import Path

import pytest


pytestmark = pytest.mark.journey

ROOT = Path(__file__).resolve().parents[2]
MIGRATION_DOC = ROOT / "docs" / "migration.md"


def test_migration_guide_covers_common_mcp_clients_without_private_paths() -> None:
    text = MIGRATION_DOC.read_text(encoding="utf-8")

    required_clients = [
        "Codex",
        "Claude Code",
        "Claude Desktop",
        "Cursor",
        "Windsurf",
        "LM Studio",
    ]
    required_commands = [
        "make config-init",
        "make config-validate",
        "make config-backup",
        "make config-render CLIENT=codex CONFIG_RENDER_APPLY=0",
        "make config-render CLIENT=codex CONFIG_RENDER_APPLY=1",
        "make config-rollback",
    ]
    required_formats = [
        "mcp_servers",
        "mcpServers",
        "command",
        "args",
        "env",
        "profiles",
        "transport",
    ]
    private_markers = [
        "/Users/",
        "$HOME/Projects",
        "$HOME/Library",
        "$HOME/Documents",
        "CloudStorage",
    ]

    assert [client for client in required_clients if client not in text] == []
    assert [command for command in required_commands if command not in text] == []
    assert [format_name for format_name in required_formats if format_name not in text] == []
    assert [marker for marker in private_markers if marker in text] == []


def test_readme_links_to_migration_guide() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "[docs/migration.md](docs/migration.md)" in readme
