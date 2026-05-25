from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib

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


def test_release_version_is_single_sourced_and_public_metadata_matches() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_init = (ROOT / "src" / "mcp_broker" / "__init__.py").read_text(encoding="utf-8")
    daemon = (ROOT / "src" / "mcp_broker" / "daemon.py").read_text(encoding="utf-8")
    upstream_stdio = (ROOT / "src" / "mcp_broker" / "upstream_stdio.py").read_text(encoding="utf-8")
    upstream_http = (ROOT / "src" / "mcp_broker" / "upstream_http.py").read_text(encoding="utf-8")
    server = json.loads((ROOT / "registry" / "server.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    package_version_match = re.search(r'__version__ = "([^"]+)"', package_init)
    assert package_version_match is not None
    package_version = package_version_match.group(1)

    assert pyproject["project"]["dynamic"] == ["version"]
    assert "version" not in pyproject["project"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "mcp_broker.__version__"
    assert package_version == "0.1.0"
    repository_match = re.fullmatch(
        r"https://github\.com/([^/]+)/([^/]+)", server["repository"]["url"]
    )
    assert repository_match is not None
    assert server["name"] == f"io.github.{repository_match.group(1)}/{repository_match.group(2)}"
    assert server["version"] == package_version
    assert server["packages"][0]["version"] == package_version
    assert server["packages"][0]["identifier"] == pyproject["project"]["name"]
    assert f"mcp-name: {server['name']}" in readme
    assert 'server_version="0.0.1"' not in daemon
    assert '"version": "0.0.1"' not in upstream_stdio
    assert '"version": "0.0.1"' not in upstream_http


def test_public_release_workflows_cover_ci_package_and_registry_publish() -> None:
    workflows = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    }

    assert set(workflows) >= {
        "ci.yml",
        "publish-pypi.yml",
        "publish-mcp-registry.yml",
    }
    assert "make precommit" in workflows["ci.yml"]
    assert "make release-smoke" in workflows["ci.yml"]
    assert "pypa/gh-action-pypi-publish" in workflows["publish-pypi.yml"]
    assert "id-token: write" in workflows["publish-pypi.yml"]
    assert "./venv-mcp-broker/bin/python - <<'PY'" in workflows["publish-mcp-registry.yml"]
    assert "cp registry/server.json server.json" in workflows["publish-mcp-registry.yml"]
    assert "mcp-publisher login github-oidc" in workflows["publish-mcp-registry.yml"]
    assert "mcp-publisher publish\n" in workflows["publish-mcp-registry.yml"]
    assert "mcp-publisher publish --file" not in workflows["publish-mcp-registry.yml"]
    assert "id-token: write" in workflows["publish-mcp-registry.yml"]


def test_package_build_targets_are_available_through_make() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "package-build:" in makefile
    assert "package-check:" in makefile
    assert "$(PYTHON) -m build" in makefile
    assert "$(PYTHON) -m twine check" in makefile
    assert "build==" in requirements
    assert "twine==" in requirements


def test_release_smoke_script_uses_tracked_public_files_only() -> None:
    script = ROOT / "scripts" / "release-smoke.sh"
    linux_script = ROOT / "scripts" / "linux-container-smoke.sh"
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    text = script.read_text(encoding="utf-8")
    linux_text = linux_script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "tar" in text
    assert "tar_option_supported" in text
    assert 'exclude=".git"' in text
    assert "make config-init" in text
    assert "make config-validate" in text
    assert "make broker-smoke" in text
    assert "/Users/" not in text
    assert "/Users/" not in (ROOT / "scripts" / "public-export.py").read_text(encoding="utf-8")
    assert '--exclude="config/broker.private.yaml"' in text
    assert "PIP_UPGRADE       ?= 0" in makefile
    assert "tar_option_supported" in linux_text
    assert "TAR_CREATE_OPTIONS" in linux_text


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
