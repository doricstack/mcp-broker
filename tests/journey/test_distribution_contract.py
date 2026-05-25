from __future__ import annotations

import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.journey

ROOT = Path(__file__).resolve().parents[2]


def test_distribution_docs_and_package_metadata_are_public_ready() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    install_doc = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    required_pyproject_terms = [
        'name = "mcp-broker"',
        'requires-python = ">=3.10"',
        "mcp-broker-client",
        "mcp-broker-daemon",
        "[project.urls]",
    ]
    required_install_terms = [
        "pipx install mcp-broker",
        "brew install",
        "make systemd-install",
        "make systemd-load",
        "make windows-install",
        "make windows-load",
        "PowerShell Scheduled Task",
    ]
    required_readme_terms = [
        "pipx install mcp-broker",
        "Homebrew",
        "systemd",
        "linux-container-smoke",
        "windows-powershell-smoke",
        "release-smoke",
    ]

    assert [term for term in required_pyproject_terms if term not in pyproject] == []
    assert [term for term in required_install_terms if term not in install_doc] == []
    assert [term for term in required_readme_terms if term not in readme] == []
    assert "/Users/" not in install_doc
    assert "$HOME/Projects" not in install_doc
    forbidden_minor_image = "python:" + ".".join(("3", "13"))
    assert forbidden_minor_image not in pyproject
    private_owner = "Navin" + "Agrawal"
    assert private_owner not in pyproject


def test_release_smoke_script_uses_tracked_public_files_only() -> None:
    script = ROOT / "scripts" / "release-smoke.sh"
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    text = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "tar" in text
    assert 'exclude=".git"' in text
    assert "make config-init" in text
    assert "make config-validate" in text
    assert "make broker-smoke" in text
    assert "/Users/" not in text
    assert '--exclude="config/broker.private.yaml"' in text
    assert "PIP_UPGRADE       ?= 0" in makefile


def test_systemd_service_contract_uses_runtime_root_and_config_path() -> None:
    script = ROOT / "scripts" / "install-systemd-user.sh"
    uninstall_script = ROOT / "scripts" / "uninstall-systemd-user.sh"
    text = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert uninstall_script.is_file()
    assert "MCP_BROKER_RUNTIME_ROOT" in text
    assert "MCP_BROKER_SOCKET" in text
    assert "MCP_BROKER_CONFIG" in text
    assert "mcp_broker.daemon" in text
    assert "broker-smoke" in text
    assert "/Users/" not in text
    assert "navin" not in text.lower()


def test_windows_scheduled_task_contract_uses_runtime_root_and_config_path() -> None:
    script = ROOT / "scripts" / "install-windows-task.ps1"
    uninstall_script = ROOT / "scripts" / "uninstall-windows-task.ps1"
    text = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert uninstall_script.is_file()
    assert "MCP_BROKER_RUNTIME_ROOT" in text
    assert "MCP_BROKER_SOCKET" in text
    assert "MCP_BROKER_CONFIG" in text
    assert "MCP_BROKER_DAEMON_COMMAND" in text
    assert "mcp_broker.daemon" in text
    assert "Register-ScheduledTask" in text
    assert "/Users/" not in text
    assert "navin" not in text.lower()


def test_config_schema_has_public_distribution_metadata() -> None:
    schema = json.loads((ROOT / "config" / "broker.schema.json").read_text(encoding="utf-8"))

    assert schema["title"] == "mcp-broker config"
    assert schema["type"] == "object"
    assert "runtime" in schema["properties"]
