from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib

import pytest

from tests.support.makefiles import read_combined_makefiles


pytestmark = pytest.mark.journey

ROOT = Path(__file__).resolve().parents[2]
SEMVER_PATTERN = re.compile(r"\b(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\b")
HISTORICAL_RELEASE_FILES = {
    "CHANGELOG.md",
    "docs/p16-maintainer-inputs.md",
}
STATIC_RELEASE_METADATA_FILES = {
    ".well-known/mcp/server-card.json",
    "docker/mcp-catalog/mcp-broker.yaml",
    "mcpb/manifest.json",
    "npm/package.json",
    "registry/server.json",
    "registry/server.template.json",
    "src/mcp_broker/__init__.py",
}


def _package_version() -> str:
    package_init = (ROOT / "src" / "mcp_broker" / "__init__.py").read_text(
        encoding="utf-8"
    )
    package_version_match = re.search(r'__version__ = "([^"]+)"', package_init)
    assert package_version_match is not None
    return package_version_match.group(1)


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


def test_mcpb_distribution_targets_package_and_smoke_bundle() -> None:
    makefile = read_combined_makefiles(ROOT)
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")

    assert re.search(
        r"^MCPB_OUTPUT\s+\?= \$\(PACKAGE_DIST_DIR\)/mcp-broker-\$\(PACKAGE_VERSION\)\.mcpb$",
        makefile,
        re.M,
    )
    assert "mcpb-pack:" in makefile
    assert "mcpb-smoke:" in makefile
    assert "mcpb-stdio-smoke:" in makefile
    assert "smithery-payload-check:" in makefile
    assert "smithery-publish:" in makefile
    assert "scripts/smithery_release.py" in makefile
    assert 'PYTHONPATH="$(PYTHONPATH)" $(PYTHON) "$(ROOT)/scripts/smithery_release.py"' in makefile
    assert "scripts/mcpb_stdio_smoke.py" in makefile
    assert '@$(NPX) -y @anthropic-ai/mcpb pack "$(ROOT)/mcpb" "$(MCPB_OUTPUT)"' in makefile
    assert '@$(NPX) -y @anthropic-ai/mcpb info "$(MCPB_SMOKE_OUTPUT)"' in makefile
    assert '@$(NPX) -y @anthropic-ai/mcpb unpack "$(MCPB_SMOKE_OUTPUT)" "$(MCPB_SMOKE_UNPACK_DIR)"' in makefile
    assert "make mcpb-pack" in distribution
    assert "make mcpb-smoke" in distribution
    assert "make mcpb-stdio-smoke" in distribution


def test_stable_release_public_status_is_aligned_to_source_release() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")
    github_publication = (ROOT / "docs" / "github-publication.md").read_text(encoding="utf-8")
    normalized_distribution = " ".join(distribution.split())

    assert "Stable release metadata is validated by `make release-version-check`" in readme
    assert "Package metadata is release-aligned by `make release-version-sync`." in distribution
    assert "PyPI: `mcp-broker $(PACKAGE_VERSION)` is published by the release transaction." in distribution
    assert (
        "MCP Registry: `io.github.NavinAgrawal/mcp-broker $(PACKAGE_VERSION)` "
        "is published and marked latest by the release transaction."
    ) in normalized_distribution
    assert (
        "Homebrew: `mcp-broker $(PACKAGE_VERSION)` is published through the public tap."
        in distribution
    )
    assert "mcp-broker $(PACKAGE_VERSION)" in github_publication


def test_current_release_versions_are_not_copied_across_docs_or_tests() -> None:
    current_version = _package_version()
    offenders: list[str] = []
    scanned_suffixes = {".md", ".py", ".sh", ".yml", ".yaml", ".json", ".toml", ".js"}
    scanned_roots = [
        ROOT / ".github",
        ROOT / ".well-known",
        ROOT / "docker",
        ROOT / "docs",
        ROOT / "mcpb",
        ROOT / "mk",
        ROOT / "npm",
        ROOT / "registry",
        ROOT / "scripts",
        ROOT / "src",
        ROOT / "tests",
    ]

    for root in scanned_roots:
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in scanned_suffixes:
                continue
            relative = str(path.relative_to(ROOT))
            if (
                relative in HISTORICAL_RELEASE_FILES
                or relative in STATIC_RELEASE_METADATA_FILES
            ):
                continue
            text = path.read_text(encoding="utf-8")
            if current_version in text:
                offenders.append(relative)

    assert offenders == []


def test_release_metadata_sync_target_is_the_only_release_bump_path() -> None:
    makefile = read_combined_makefiles(ROOT)
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "sync_release_metadata.py").read_text(encoding="utf-8")

    assert "release-version-resolve:" in makefile
    assert "release-version-sync:" in makefile
    assert "RELEASE_BUMP ?=" in makefile
    assert "scripts/sync_release_metadata.py" in makefile
    assert "--bump \"$(RELEASE_BUMP)\"" in makefile
    assert "--emit-version" in makefile
    assert "release-version-resolve RELEASE_BUMP=patch" in distribution
    assert "import logging" in script
    assert "print(" not in script


def test_public_release_workflows_cover_ci_package_and_registry_publish() -> None:
    workflows = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    }

    assert set(workflows) == {"ci.yml", "publish-everywhere.yml"}
    assert "make precommit" in workflows["ci.yml"]
    assert "make release-smoke" in workflows["ci.yml"]
    assert "make release RELEASE_APPLY=1" in workflows["publish-everywhere.yml"]
    assert "release_version:" in workflows["publish-everywhere.yml"]
    assert "release_bump:" in workflows["publish-everywhere.yml"]
    assert "RELEASE_VERSION=$version" in workflows["publish-everywhere.yml"]
    assert "make --no-print-directory release-version-resolve" in workflows["publish-everywhere.yml"]
    assert 'RELEASE_VERSION="$RELEASE_VERSION"' in workflows["publish-everywhere.yml"]
    assert "make publish-version-check" in workflows["ci.yml"]
    assert "make npm-package-check" in workflows["ci.yml"]
    assert "make npm-smoke" in workflows["ci.yml"]
    assert "release:" in workflows["publish-everywhere.yml"]
    assert "published" in workflows["publish-everywhere.yml"]
    assert "id-token: write" in workflows["publish-everywhere.yml"]
    assert "packages: write" in workflows["publish-everywhere.yml"]
    assert "PYTEST_MARKER_EXPRESSION:" not in workflows["publish-everywhere.yml"]
    assert "publish-pypi.yml" not in workflows
    assert "publish-python.yml" not in workflows
    assert "publish-mcp-registry.yml" not in workflows


def test_package_build_targets_are_available_through_make() -> None:
    makefile = read_combined_makefiles(ROOT)
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    normalized_requirements = {
        line.strip()
        for line in requirements.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert "package-build:" in makefile
    assert "package-check:" in makefile
    assert "$(PYTHON) -m build" in makefile
    assert "$(PYTHON) -m twine check" in makefile
    assert "build==" in requirements
    assert "twine==" in requirements
    assert "pytest==9.0.3" in requirements
    assert "pytest-xdist==3.8.0" in requirements
    assert pyproject["project"]["license"] == "MIT"
    assert pyproject["project"]["authors"] == [{"name": "Navin B Agrawal"}]
    for dependency in pyproject["project"]["dependencies"]:
        package_name = re.split(r"[<>=~!]", dependency, maxsplit=1)[0]
        assert any(line.startswith(package_name + "==") for line in normalized_requirements)


def test_docker_distribution_has_oci_labels_and_multi_arch_release_target() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    makefile = read_combined_makefiles(ROOT)
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
    assert 'org.opencontainers.image.licenses="MIT"' in dockerfile
    assert 'org.opencontainers.image.authors="Navin B Agrawal"' in dockerfile

    for term in [
        "docker-buildx:",
        "DOCKER_PLATFORMS",
        "--sbom=$(DOCKER_SBOM)",
        "--provenance=$(DOCKER_PROVENANCE)",
        "--platform \"$(DOCKER_PLATFORMS)\"",
    ]:
        assert term in makefile

    assert 'SBOM_ARG="false"' in makefile
    assert 'PROVENANCE_ARG="false"' in makefile

    assert "SBOM" in distribution
    assert "provenance" in distribution
    assert "linux/amd64,linux/arm64" in distribution


def test_npm_and_docker_distribution_decisions_are_recorded() -> None:
    npm_doc = (ROOT / "docs" / "npm-distribution.md").read_text(encoding="utf-8")
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")
    maintainer_inputs_path = ROOT / "docs" / "p16-maintainer-inputs.md"
    allowlist_path = ROOT / "public-export" / "allowlist.txt"

    assert "`mcp-broker` on NPM is a different project" in npm_doc
    assert "`@navinagrawal/mcp-broker`" in npm_doc
    assert "does not reimplement the Python broker in Node" in npm_doc
    assert "NPM trusted publishing is the preferred auth path" in npm_doc
    assert "NPM is an optional bridge package" in distribution
    assert "Current source release: `$(PACKAGE_VERSION)`" in distribution
    assert "docker.io/navinagrawal/mcp-broker" in distribution
    assert "ghcr.io/navinagrawal/mcp-broker" in distribution
    assert "Docker Hub is the primary image for Docker MCP Catalog work" in distribution
    if maintainer_inputs_path.exists():
        maintainer_inputs = maintainer_inputs_path.read_text(encoding="utf-8")
        assert "Do not publish unscoped `mcp-broker` to NPM" in maintainer_inputs
    if allowlist_path.exists():
        assert "docs/npm-distribution.md" in allowlist_path.read_text(encoding="utf-8")


def test_publish_everywhere_is_single_release_orchestrator() -> None:
    makefile = read_combined_makefiles(ROOT)
    npm_doc = (ROOT / "docs" / "npm-distribution.md").read_text(encoding="utf-8")
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")
    distribution_plan_path = (
        ROOT / "docs" / "plans" / "2026-05-26-npm-docker-distribution.md"
    )
    workflow = (ROOT / ".github" / "workflows" / "publish-everywhere.yml").read_text(
        encoding="utf-8"
    )

    for target in [
        "release-version-check:",
        "release-check:",
        "release:",
        "package-install-smoke:",
        "public-stable-surface-smoke:",
        "public-release-surface-smoke:",
        "publish-everywhere-check:",
        "publish-everywhere:",
        "_publish-everywhere-pypi:",
        "_publish-everywhere-npm:",
        "_publish-everywhere-docker:",
        "_publish-everywhere-mcp-registry:",
        "_publish-everywhere-homebrew:",
        "docker-mcp-catalog-smoke:",
        "docker-publish-check:",
        "docker-release-smoke:",
        "publish-version-check:",
    ]:
        assert target in makefile

    for target in [
        "publish-pypi:",
        "publish-npm:",
        "publish-docker-images:",
        "publish-mcp-registry:",
    ]:
        assert target not in makefile

    assert "scripts/check_release_versions.py" in makefile
    assert "PUBLIC_RELEASE_PYTEST_MARKER_EXPRESSION ?= not private_contract" in makefile
    assert "RELEASE_GATE_PYTEST_MARKER_EXPRESSION ?=" in makefile
    assert "scripts/update_homebrew_formula.py" in makefile
    assert "scripts/public-surface-smoke.sh" in makefile
    assert "pipx run --spec \"mcp-broker==$" in makefile
    assert '"$(UVX)" --from "mcp-broker==$' in makefile
    assert "PUBLIC_SURFACE_REQUIRE_NPM=1" in makefile
    assert "PUBLIC_SURFACE_REQUIRE_DOCKER=1" in makefile
    assert "PYPI_VERSION_URL" in makefile
    assert "PyPI package already exists" in makefile
    assert '$(NPM) view "$(NPM_PACKAGE_NAME)@$(PACKAGE_VERSION)" version' in makefile
    assert "NPM package already exists" in makefile
    assert "MCP_REGISTRY_SEARCH_URL" in makefile
    assert "MCP Registry metadata already exists" in makefile
    assert "HOMEBREW_TAP_TOKEN" in makefile
    assert "Homebrew formula already current" in makefile
    assert "--pypi-attempts \"$(HOMEBREW_PYPI_ATTEMPTS)\"" in makefile
    assert "GIT_ASKPASS=\"$$tmpdir/git-askpass.sh\"" in makefile
    assert "extraheader=\"AUTHORIZATION: bearer $${HOMEBREW_TAP_TOKEN}\"" not in makefile
    assert "x-access-token:$${HOMEBREW_TAP_TOKEN}" not in makefile
    assert "publish-version-check" in makefile
    assert '"$(UV)" publish --trusted-publishing always' in makefile
    assert "$(NPM) publish --access public --provenance" in makefile
    assert "--push" in makefile
    assert "mcp-publisher login github-oidc" in makefile
    assert "make release RELEASE_APPLY=1" in workflow
    assert "make publish-everywhere PUBLISH_EVERYWHERE_APPLY=1" not in workflow
    assert "release:" in workflow
    assert "published" in workflow
    assert "id-token: write" in workflow
    assert "packages: write" in workflow
    assert "DOCKERHUB_USERNAME" in workflow
    assert "DOCKERHUB_TOKEN" in workflow
    assert "NODE_AUTH_TOKEN" not in workflow
    assert "NPM_TOKEN" not in workflow
    assert 'node-version: "24"' in workflow
    assert "astral-sh/setup-uv" in workflow
    assert "actions/setup-node" in workflow
    assert "docker/setup-buildx-action" in workflow
    assert "docker/setup-buildx-action@v4" in workflow
    assert "docker/login-action@v4" in workflow
    assert "docker/setup-buildx-action@v3" not in workflow
    assert "docker/login-action@v3" not in workflow
    assert "docker/login-action" in workflow
    assert "uv publish" not in workflow
    assert "npm publish" not in workflow
    assert "docker buildx build" not in workflow
    assert "mcp-publisher publish" not in workflow
    assert "workflow_run:" not in workflow
    assert "push:" not in workflow
    assert ".github/workflows/publish-everywhere.yml" in npm_doc
    assert ".github/workflows/publish-npm.yml" not in npm_doc
    assert "NPM_TOKEN" not in npm_doc
    assert "NODE_AUTH_TOKEN" not in npm_doc
    assert "first publish returned `E404`" not in npm_doc
    assert ".github/workflows/publish-pypi.yml" not in distribution
    assert ".github/workflows/publish-python.yml" not in distribution
    assert ".github/workflows/publish-mcp-registry.yml" not in distribution
    assert "Manual per-registry workflows remain" not in distribution
    if distribution_plan_path.exists():
        distribution_plan = distribution_plan_path.read_text(encoding="utf-8")
        assert ".github/workflows/publish-docker.yml" not in distribution_plan
        assert 'assert "npm publish" in workflow' not in distribution_plan
        assert 'assert "make docker-publish-check" in workflow' not in distribution_plan
        assert "Manual per-registry workflows remain" not in distribution_plan
        assert "publish-pypi" not in distribution_plan
        assert "publish-npm" not in distribution_plan
        assert "publish-docker-images" not in distribution_plan
        assert "publish-mcp-registry" not in distribution_plan
        assert "fallbacks only" not in distribution_plan
        assert "Push `1.0.0` and semver aliases" not in distribution_plan


def test_publish_everywhere_orchestration_is_sequenced_and_parallel() -> None:
    makefile = read_combined_makefiles(ROOT)

    release_section = makefile.split("_release-impl:", maxsplit=1)[1].split(
        "publish-version-check:",
        maxsplit=1,
    )[0]
    release_check_section = makefile.split("release-check:", maxsplit=1)[1].split(
        "publish-everywhere-check:",
        maxsplit=1,
    )[0]
    check_section = makefile.split("publish-everywhere-check:", maxsplit=1)[1].split(
        "publish-everywhere:",
        maxsplit=1,
    )[0]
    publish_section = makefile.split("publish-everywhere:", maxsplit=1)[1].split(
        "_publish-everywhere-pypi:",
        maxsplit=1,
    )[0]
    pypi_index = publish_section.index("_publish-everywhere-pypi")
    fanout_index = publish_section.index("_publish-everywhere-npm _publish-everywhere-docker _publish-everywhere-mcp-registry")

    assert "PUBLISH_CHECK_JOBS ?= 2" in makefile
    assert "PUBLISH_EVERYWHERE_JOBS ?= 4" in makefile
    assert "RELEASE_APPLY ?= 0" in makefile
    assert "RELEASE_VERSION ?=" in makefile
    assert "PYPI_PROJECT_NAME ?= mcp-broker" in makefile
    assert "PYPI_VERSION_URL ?= https://pypi.org/pypi/$(PYPI_PROJECT_NAME)/$(PACKAGE_VERSION)/json" in makefile
    assert "MCP_REGISTRY_NAME ?= io.github.NavinAgrawal/mcp-broker" in makefile
    assert "MCP_REGISTRY_SEARCH_URL ?= https://registry.modelcontextprotocol.io/v0.1/servers?search=$(MCP_REGISTRY_NAME)" in makefile
    assert "release-version-check" in release_check_section
    assert "publish-everywhere-check" in release_check_section
    assert "directory-submission-check mcpb-smoke smithery-payload-check" in release_check_section
    assert '$(call timed_make,"release-check: publish preflight",publish-everywhere-check)' in release_check_section
    assert '$(call timed_make,"release-check: directory and bundle metadata",-j $(PUBLISH_CHECK_JOBS) directory-submission-check mcpb-smoke smithery-payload-check)' in release_check_section
    assert '$(call timed_make,"release: preflight",release-check)' in release_section
    assert '$(call timed_make,"release: publish",PUBLISH_EVERYWHERE_APPLY=1 PUBLISH_EVERYWHERE_SKIP_CHECKS=1 publish-everywhere)' in release_section
    assert "publish-version-check" in check_section
    release_gate_index = check_section.index("release-gate")
    publish_check_fanout_index = check_section.index("npm-package-check npm-smoke _publish-check-docker-smoke _publish-check-docker-buildx")
    assert "_publish-check-docker-smoke:" in makefile
    assert "_publish-check-docker-buildx:" in makefile
    assert "_publish-everywhere-required-env-check:" in makefile
    assert '$(call timed_make,"publish-everywhere-check: release gate",PYTEST_MARKER_EXPRESSION="$(RELEASE_GATE_PYTEST_MARKER_EXPRESSION)" release-gate)' in check_section
    assert '$(call timed_make,"publish-everywhere-check: package smoke children",-j $(PUBLISH_CHECK_JOBS) npm-package-check npm-smoke _publish-check-docker-smoke _publish-check-docker-buildx)' in check_section
    assert release_gate_index < publish_check_fanout_index
    assert 'docker-smoke DOCKER_IMAGE="mcp-broker:publish-check"' in makefile
    assert 'docker-buildx DOCKER_IMAGE="mcp-broker:buildx-check" DOCKER_PLATFORMS="$(DOCKER_LOCAL_PLATFORM)"' in makefile
    assert '$(call timed_make,"publish-everywhere: required env",_publish-everywhere-required-env-check)' in publish_section
    assert publish_section.index("_publish-everywhere-required-env-check") < pypi_index
    assert "HOMEBREW_TAP_TOKEN is required before publish-everywhere starts" in makefile
    assert '$(call timed_make,"publish-everywhere: pypi",_publish-everywhere-pypi)' in publish_section
    assert '$(call timed_make,"publish-everywhere: parallel registries",-j $(PUBLISH_EVERYWHERE_JOBS) _publish-everywhere-npm _publish-everywhere-docker _publish-everywhere-mcp-registry _publish-everywhere-homebrew)' in publish_section
    assert "PUBLISH_EVERYWHERE_SKIP_CHECKS ?= 0" in makefile
    assert "publish-everywhere: preflight checks skipped" in makefile
    assert pypi_index < fanout_index
    assert 'docker buildx build \\' in makefile
    assert '$(call timed_make,"publish child: docker-publish-check",docker-publish-check)' in makefile
    assert "\n\t+@label=\"$(call strip_quotes,$(1))\"" in makefile
    assert "\n\t@label=\"$(call strip_quotes,$(1))\"" not in makefile


def test_docker_mcp_catalog_smoke_uses_file_metadata_boundary() -> None:
    makefile = read_combined_makefiles(ROOT)
    catalog_file = ROOT / "docker" / "mcp-catalog" / "mcp-broker.yaml"
    catalog_text = catalog_file.read_text(encoding="utf-8")
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")

    for term in [
        "name: mcp-broker",
        "title: mcp-broker",
        "type: server",
        f"image: docker.io/navinagrawal/mcp-broker:{_package_version()}",
        "description: Local MCP broker",
    ]:
        assert term in catalog_text

    assert "docker-mcp-catalog-smoke:" in makefile
    assert "docker mcp catalog create" in makefile
    assert "--server \"file://$(DOCKER_MCP_CATALOG_FILE)\"" in makefile
    assert "docker mcp catalog server ls" in makefile
    assert "docker mcp catalog remove" in makefile
    assert "DOCKER_MCP_CATALOG_FILE ?= $(ROOT)/docker/mcp-catalog/mcp-broker.yaml" in makefile
    assert "DOCKER_MCP_CATALOG_REF ?= mcp-broker-local-catalog:local" in makefile
    release_smoke = re.search(
        r"(?ms)^docker-release-smoke:.*?(?=^[A-Za-z0-9_.-]+:|\Z)",
        makefile,
    )
    assert release_smoke is not None
    release_smoke_body = release_smoke.group(0)
    assert '> "$(TEST_LOG_DIR)/docker-release-smoke.jsonl"' in release_smoke_body
    assert 'grep -q \'"tools"\' "$(TEST_LOG_DIR)/docker-release-smoke.jsonl"' in release_smoke_body
    assert '| grep -q \'"tools"\'' not in release_smoke_body
    assert "Docker MCP Toolkit custom catalog smoke uses file-based server metadata" in distribution
    assert "The Docker image itself is not treated as self-describing" in distribution


def test_docker_mcp_registry_submission_packet_is_staged() -> None:
    submission = (ROOT / "docs" / "docker-mcp-registry-submission.md").read_text(
        encoding="utf-8"
    )
    catalog = ROOT / "docker" / "mcp-catalog" / "mcp-broker.yaml"

    for term in [
        "docker.io/navinagrawal/mcp-broker:$(PACKAGE_VERSION)",
        "ghcr.io/navinagrawal/mcp-broker:$(PACKAGE_VERSION)",
        "make docker-smoke",
        "make docker-mcp-catalog-smoke",
        "No hidden host client config writes",
        "PR submitted and pending external Docker review",
        "https://github.com/docker/mcp-registry/pull/3819",
        "mergeStateStatus=BLOCKED",
        "REVIEW_REQUIRED",
    ]:
        assert term in submission

    assert catalog.is_file()


def test_public_surface_smoke_downloads_real_public_artifacts() -> None:
    script = (ROOT / "scripts" / "public-surface-smoke.sh").read_text(encoding="utf-8")
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")

    assert "PYTHONPATH=\"\"" in script
    assert "DOCKER_OUTPUT=" in script
    assert "grep -q '\"tools\"' \"$DOCKER_OUTPUT\"" in script
    for term in [
        "mktemp -d",
        "pip install \"mcp-broker==$PUBLIC_SURFACE_VERSION\"",
        "pipx run --spec \"mcp-broker==$PUBLIC_SURFACE_VERSION\"",
        "uvx --from \"mcp-broker==$PUBLIC_SURFACE_VERSION\"",
        "github.com/NavinAgrawal/mcp-broker/archive/refs/tags/v$PUBLIC_SURFACE_VERSION.tar.gz",
        "HOMEBREW_CACHE=\"$WORK_DIR/homebrew-cache\"",
        "brew update --force --quiet",
        "brew fetch --formula NavinAgrawal/tap/mcp-broker",
        "brew upgrade NavinAgrawal/tap/mcp-broker",
        "brew list --formula --versions mcp-broker",
        "brew test NavinAgrawal/tap/mcp-broker",
        "registry.modelcontextprotocol.io/v0.1/servers?search=",
        "npm view \"$NPM_PACKAGE_NAME@$PUBLIC_SURFACE_VERSION\"",
        "docker buildx imagetools inspect \"$DOCKER_RELEASE_IMAGE\"",
    ]:
        assert term in script

    assert "public-stable-surface-smoke" in distribution
    assert "public-release-surface-smoke" in distribution
    assert "downloads into a temporary directory" in distribution


def test_p16_p18_tracking_has_no_stale_repo_owned_pending_rows() -> None:
    todo_path = ROOT / "TODO.md"
    todo = todo_path.read_text(encoding="utf-8") if todo_path.exists() else ""
    maintainer_inputs_path = ROOT / "docs" / "p16-maintainer-inputs.md"
    maintainer_inputs = (
        maintainer_inputs_path.read_text(encoding="utf-8")
        if maintainer_inputs_path.exists()
        else ""
    )
    plan_path = ROOT / "docs" / "plans" / "2026-05-26-npm-docker-distribution.md"
    plan = plan_path.read_text(encoding="utf-8") if plan_path.exists() else ""

    if todo:
        assert "- [x] Validate `pipx` and `uvx` against the published PyPI package." in todo
    if maintainer_inputs:
        assert "pipx validation date: 2026-05-27" in maintainer_inputs
        assert "uv validation date: 2026-05-27" in maintainer_inputs
        assert "Status: complete for `$(PACKAGE_VERSION)`." in maintainer_inputs
        assert "publication pending" not in maintainer_inputs
        assert "NPM_TOKEN" not in maintainer_inputs
        assert "NODE_AUTH_TOKEN" not in maintainer_inputs
        assert "Status: pending for `1.0.0`." not in maintainer_inputs
        assert "Source changes pending" not in maintainer_inputs
        assert "8326 mutants" not in maintainer_inputs
        assert "`8332` mutants" in maintainer_inputs
    if plan:
        assert "## Progress" in plan
        assert "- [x] Task 4: NPM publication completed through package bootstrap and trusted publishing." in plan
        assert "- [x] Task 7: Docker images published to Docker Hub and GHCR." in plan
        assert "- [x] Task 8: Docker MCP Catalog custom catalog smoke." in plan
        assert "- [x] Task 9: Docker MCP Registry PR packet staged." in plan
        assert "NPM_TOKEN" not in plan
        assert "publication remains external" not in plan


def test_release_version_checker_uses_logging_instead_of_print() -> None:
    script = (ROOT / "scripts" / "check_release_versions.py").read_text(encoding="utf-8")

    assert "import logging" in script
    assert "LOGGER = logging.getLogger" in script
    assert '"registry/server.template.json"' in script
    assert '"mcp_registry_template"' in script
    assert '"mcp_registry_template_package"' in script
    assert "print(" not in script


def test_public_runtime_and_release_docs_do_not_use_python_print() -> None:
    scanned_roots = [
        ROOT / "src",
        ROOT / "scripts",
        ROOT / "npm",
        ROOT / "docs",
        ROOT / ".github" / "workflows",
    ]
    scanned_suffixes = {".md", ".py", ".js", ".json", ".sh", ".toml", ".yml", ".yaml"}
    offenders: list[str] = []

    for root in scanned_roots:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in scanned_suffixes:
                if "print(" in path.read_text(encoding="utf-8"):
                    offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_release_smoke_script_uses_tracked_public_files_only() -> None:
    script = ROOT / "scripts" / "release-smoke.sh"
    linux_script = ROOT / "scripts" / "linux-container-smoke.sh"
    linux_release_gate_script = ROOT / "scripts" / "linux-release-gate.sh"
    makefile = read_combined_makefiles(ROOT)
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
