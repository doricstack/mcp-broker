from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib

import pytest


pytestmark = pytest.mark.journey

ROOT = Path(__file__).resolve().parents[2]
STABLE_RELEASE_VERSION = "1.0.0"


def test_distribution_docs_and_package_metadata_are_public_ready() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    install_doc = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    required_pyproject_terms = [
        'name = "mcp-broker"',
        'requires-python = ">=3.10"',
        "Local MCP broker for sharing upstream MCP servers across MCP clients",
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
    assert "https://github.com/NavinAgrawal/mcp-broker" in pyproject
    assert "Codex and Claude sessions" not in pyproject
    assert "to Codex and Claude." not in readme
    assert "Renders Codex and Claude MCP config entries" not in readme


def test_release_version_is_single_sourced_and_public_metadata_matches() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    package_init = (ROOT / "src" / "mcp_broker" / "__init__.py").read_text(encoding="utf-8")
    daemon = (ROOT / "src" / "mcp_broker" / "daemon.py").read_text(encoding="utf-8")
    upstream_stdio = (ROOT / "src" / "mcp_broker" / "upstream_stdio.py").read_text(encoding="utf-8")
    upstream_http = (ROOT / "src" / "mcp_broker" / "upstream_http.py").read_text(encoding="utf-8")
    server = json.loads((ROOT / "registry" / "server.json").read_text(encoding="utf-8"))
    server_template = json.loads((ROOT / "registry" / "server.template.json").read_text(encoding="utf-8"))
    mcpb_manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    package_version_match = re.search(r'__version__ = "([^"]+)"', package_init)
    assert package_version_match is not None
    package_version = package_version_match.group(1)
    latest_changelog_match = re.search(r"^## ([0-9]+\.[0-9]+\.[0-9]+) - ", changelog, re.M)
    assert latest_changelog_match is not None

    assert pyproject["project"]["dynamic"] == ["version"]
    assert "version" not in pyproject["project"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"] == "mcp_broker.__version__"
    assert package_version == STABLE_RELEASE_VERSION
    assert package_version == latest_changelog_match.group(1)
    repository_match = re.fullmatch(
        r"https://github\.com/([^/]+)/([^/]+)", server["repository"]["url"]
    )
    assert repository_match is not None
    assert server["name"] == f"io.github.{repository_match.group(1)}/{repository_match.group(2)}"
    assert server["version"] == package_version
    assert server["packages"][0]["version"] == package_version
    assert server_template["version"] == package_version
    assert server_template["packages"][0]["version"] == package_version
    assert mcpb_manifest["version"] == package_version
    assert server["packages"][0]["identifier"] == pyproject["project"]["name"]
    assert pyproject["project"]["urls"]["Homepage"] == server["repository"]["url"]
    assert pyproject["project"]["urls"]["Documentation"] == f"{server['repository']['url']}#readme"
    assert pyproject["project"]["urls"]["Issues"] == f"{server['repository']['url']}/issues"
    assert f"mcp-name: {server['name']}" in readme
    assert 'server_version="0.0.1"' not in daemon
    assert '"version": "0.0.1"' not in upstream_stdio
    assert '"version": "0.0.1"' not in upstream_http


def test_stable_release_public_status_is_aligned_to_1_0_0() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")
    github_publication = (ROOT / "docs" / "github-publication.md").read_text(encoding="utf-8")
    normalized_distribution = " ".join(distribution.split())

    assert f"Stable release metadata is prepared for `{STABLE_RELEASE_VERSION}`" in readme
    assert f"Package metadata is release-aligned for `{STABLE_RELEASE_VERSION}`." in distribution
    assert f"PyPI: `mcp-broker {STABLE_RELEASE_VERSION}` metadata is prepared." in distribution
    assert (
        f"MCP Registry: `io.github.NavinAgrawal/mcp-broker {STABLE_RELEASE_VERSION}` "
        "metadata is prepared."
    ) in normalized_distribution
    assert f"Homebrew: the public tap must be refreshed to `{STABLE_RELEASE_VERSION}`" in distribution
    assert f"mcp-broker {STABLE_RELEASE_VERSION}" in github_publication


def test_public_release_workflows_cover_ci_package_and_registry_publish() -> None:
    workflows = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    }

    assert set(workflows) >= {
        "ci.yml",
        "publish-python.yml",
        "publish-pypi.yml",
        "publish-mcp-registry.yml",
    }
    assert "make precommit" in workflows["ci.yml"]
    assert "make release-smoke" in workflows["ci.yml"]
    assert "make release-gate" in workflows["publish-pypi.yml"]
    assert "make precommit RUNTIME_ROOT" not in workflows["publish-pypi.yml"]
    assert "pypa/gh-action-pypi-publish" in workflows["publish-pypi.yml"]
    assert "skip-existing: true" in workflows["publish-pypi.yml"]
    assert "id-token: write" in workflows["publish-pypi.yml"]
    assert "tags:" in workflows["publish-pypi.yml"]
    assert '"v*"' in workflows["publish-pypi.yml"]
    assert "repository_dispatch:" in workflows["publish-pypi.yml"]
    assert "publish-pypi" in workflows["publish-pypi.yml"]
    assert "make release-gate" in workflows["publish-python.yml"]
    assert "pypa/gh-action-pypi-publish" in workflows["publish-python.yml"]
    assert "id-token: write" in workflows["publish-python.yml"]
    assert "publish-python" in workflows["publish-python.yml"]
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


def test_docker_distribution_has_oci_labels_and_multi_arch_release_target() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")

    for term in [
        "ARG VERSION=",
        "ARG VCS_REF=",
        "ARG SOURCE_URL=",
        "org.opencontainers.image.title",
        "org.opencontainers.image.version",
        "org.opencontainers.image.revision",
        "org.opencontainers.image.source",
        "org.opencontainers.image.licenses",
    ]:
        assert term in dockerfile

    for term in [
        "docker-buildx:",
        "DOCKER_PLATFORMS",
        "--sbom=$(DOCKER_SBOM)",
        "--provenance=$(DOCKER_PROVENANCE)",
        "--platform \"$(DOCKER_PLATFORMS)\"",
    ]:
        assert term in makefile

    assert "SBOM" in distribution
    assert "provenance" in distribution
    assert "linux/amd64,linux/arm64" in distribution


def test_release_smoke_script_uses_tracked_public_files_only() -> None:
    script = ROOT / "scripts" / "release-smoke.sh"
    linux_script = ROOT / "scripts" / "linux-container-smoke.sh"
    linux_release_gate_script = ROOT / "scripts" / "linux-release-gate.sh"
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    text = script.read_text(encoding="utf-8")
    linux_text = linux_script.read_text(encoding="utf-8")
    linux_release_gate_text = linux_release_gate_script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "scripts/public-export.py" in text
    assert "--allowlist" in text
    assert "--denylist" in text
    assert "--exclude venv-mcp-broker" in text
    assert "--exclude var" in text
    assert "make config-init" in text
    assert "make config-validate" in text
    assert "make broker-smoke" in text
    assert 'XDG_CONFIG_HOME="$XDG_CONFIG_HOME_DIR"' in text
    assert "/Users/" not in text
    export_helper = ROOT / "scripts" / "public-export.py"
    if export_helper.exists():
        assert "/Users/" not in export_helper.read_text(encoding="utf-8")
    assert "config/broker.private.yaml" not in text
    assert "PIP_UPGRADE       ?= 0" in makefile
    assert "tar_option_supported" in linux_text
    assert "TAR_CREATE_OPTIONS" in linux_text
    assert "linux-release-gate" in makefile
    assert "make release-gate" in linux_release_gate_text
    assert "GITHUB_ACTIONS=true" in linux_release_gate_text
    assert "XDG_CONFIG_HOME=/tmp/home/.config" in linux_release_gate_text
    assert "git init -q" in linux_release_gate_text
    assert "git ls-files -co --exclude-standard -z" in linux_release_gate_text
    assert "git config --global --add safe.directory /workspace" in linux_release_gate_text
    assert "git add ." in linux_release_gate_text
    assert "--exclude=\"var/coverage/*\"" not in linux_release_gate_text
    assert "/Users/" not in linux_release_gate_text


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
