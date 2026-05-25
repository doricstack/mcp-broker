from __future__ import annotations

from pathlib import Path

import pytest


pytestmark = pytest.mark.journey

ROOT = Path(__file__).resolve().parents[2]


def test_public_landing_surface_exists_and_is_generic() -> None:
    required_paths = [
        "README.md",
        "LICENSE",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "ROADMAP.md",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/config_help.md",
        ".github/ISSUE_TEMPLATE/upstream_compatibility.md",
        ".github/pull_request_template.md",
        "docs/context-reduction-measurement.md",
        "docs/comparison.md",
        "docs/adoption-guide.md",
        "docs/safety.md",
        "docs/distribution.md",
        "docs/directory-submission-packet.md",
        "docs/github-publication.md",
        "docs/launch.md",
        "docs/community-launch.md",
        "docs/public-readiness.md",
        ".well-known/mcp/server-card.json",
        "registry/server.json",
        "registry/server.template.json",
    ]
    missing = [path for path in required_paths if not (ROOT / path).is_file()]

    assert missing == []


def test_readme_public_first_screen_has_adoption_content() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required_terms = [
        "one local MCP entry",
        "609",
        "43",
        "92.94%",
        "276,989",
        "45,281",
        "83.65%",
        "## Quickstart",
        "## Architecture",
        "## Comparison",
        "## Screenshots Or GIF",
        "SECURITY.md",
        "CONTRIBUTING.md",
    ]
    forbidden_terms = [
        "Claude config rendering exists, but Claude should not be wired",
        "/Users/",
        "$HOME/Projects",
        "CloudStorage",
    ]

    assert [term for term in required_terms if term not in readme] == []
    assert [term for term in forbidden_terms if term in readme] == []


def test_public_metadata_docs_are_ready_for_first_release() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    readiness = (ROOT / "docs" / "public-readiness.md").read_text(encoding="utf-8")

    assert "## 0.1.0" in changelog
    assert "context-reduction-measurement.md" in changelog
    assert "Private-To-Public Export" in roadmap
    assert "GitHub topics" in readiness
    assert "mcp, model-context-protocol, codex, claude" in readiness
    assert "/Users/" not in changelog
    assert "/Users/" not in roadmap
    assert "/Users/" not in readiness


def test_public_safety_docs_cover_broker_mediated_risks() -> None:
    security = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    required_security_terms = [
        "mutating tools",
        "OAuth state",
        "browser state",
        "filesystem roots",
        "database URLs",
        "per-profile allowlists",
        "config/broker.private.yaml",
    ]
    required_contributing_terms = [
        "Public repo first",
        "make quality-gate",
        "config/broker.example.yaml",
        "Do not commit local MCP inventory",
    ]

    assert [term for term in required_security_terms if term not in security] == []
    assert [term for term in required_contributing_terms if term not in contributing] == []


def test_public_adoption_guides_cover_comparison_adoption_and_safety() -> None:
    comparison = (ROOT / "docs" / "comparison.md").read_text(encoding="utf-8")
    adoption = (ROOT / "docs" / "adoption-guide.md").read_text(encoding="utf-8")
    safety = (ROOT / "docs" / "safety.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    required_comparison_terms = [
        "Docker MCP Gateway",
        "IBM ContextForge",
        "Microsoft MCP Gateway",
        "Smithery",
        "Glama Gateway",
        "simple MCP proxies",
    ]
    required_adoption_terms = [
        "Codex",
        "Claude",
        "Cursor",
        "too many MCP tools loaded",
        "compact broker facade",
    ]
    required_safety_terms = [
        "mutating tools",
        "OAuth state",
        "browser state",
        "filesystem roots",
        "database URLs",
        "per-profile allowlists",
    ]

    assert [term for term in required_comparison_terms if term not in comparison] == []
    assert [term for term in required_adoption_terms if term not in adoption] == []
    assert [term for term in required_safety_terms if term not in safety] == []
    assert "docs/comparison.md" in readme
    assert "docs/adoption-guide.md" in readme
    assert "docs/safety.md" in readme


def test_public_distribution_docs_cover_package_registry_and_directory_paths() -> None:
    install = (ROOT / "docs" / "install.md").read_text(encoding="utf-8")
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")
    github_publication = (ROOT / "docs" / "github-publication.md").read_text(encoding="utf-8")
    community_launch = (ROOT / "docs" / "community-launch.md").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    required_install_terms = [
        "pipx install mcp-broker",
        "uv tool install mcp-broker",
        "mcp-broker init",
        "mcp-broker start",
        "mcp-broker status",
        "mcp-broker render codex --dry-run",
    ]
    required_distribution_terms = [
        "MCP Registry",
        "mcp-publisher",
        "server.json",
        "Docker MCP Toolkit",
        "Smithery",
        "Glama",
        "PulseMCP",
        "Homebrew",
    ]
    required_publication_terms = [
        "repository description",
        "model-context-protocol",
        "pinned demo issue",
        "first release notes",
    ]
    required_community_terms = [
        "GitHub Discussions",
        "Hacker News",
        "r/mcp",
        "r/LocalLLaMA",
        "feedback labels",
    ]

    assert [term for term in required_install_terms if term not in install] == []
    assert [term for term in required_distribution_terms if term not in distribution] == []
    assert [term for term in required_publication_terms if term not in github_publication] == []
    assert [term for term in required_community_terms if term not in community_launch] == []
    assert 'mcp-broker = "mcp_broker.cli:main"' in pyproject
    assert '"share/mcp-broker/config" = ["config/broker.example.yaml"]' in pyproject


def test_registry_template_is_public_safe_and_points_to_pypi_package() -> None:
    import json

    template = json.loads((ROOT / "registry" / "server.template.json").read_text(encoding="utf-8"))
    raw = (ROOT / "registry" / "server.template.json").read_text(encoding="utf-8")

    assert template["$schema"] == "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    assert template["name"] == "io.github.example/mcp-broker"
    assert template["packages"][0]["registryType"] == "pypi"
    assert template["packages"][0]["identifier"] == "mcp-broker"
    assert template["packages"][0]["transport"]["type"] == "stdio"
    assert "/Users/" not in raw
    assert "CloudStorage" not in raw


def test_registry_metadata_and_server_card_are_public_ready() -> None:
    import json

    server = json.loads((ROOT / "registry" / "server.json").read_text(encoding="utf-8"))
    template = json.loads((ROOT / "registry" / "server.template.json").read_text(encoding="utf-8"))
    card = json.loads((ROOT / ".well-known" / "mcp" / "server-card.json").read_text(encoding="utf-8"))
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")
    packet = (ROOT / "docs" / "directory-submission-packet.md").read_text(encoding="utf-8")
    launch = (ROOT / "docs" / "launch.md").read_text(encoding="utf-8")

    assert server["$schema"] == "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    assert server["name"].startswith("io.github.")
    assert server["packages"][0]["registryType"] == "pypi"
    assert server["packages"][0]["identifier"] == "mcp-broker"
    assert server["packages"][0]["transport"]["type"] == "stdio"
    assert template["name"] == "io.github.example/mcp-broker"
    assert card["name"] == server["name"]
    assert card["packages"][0]["identifier"] == "mcp-broker"
    assert "GitHub OIDC" in distribution
    assert "PyPI package must exist first" in distribution
    assert "mcpservers.org" in packet
    assert "mcp.so" in packet
    assert "MCPCentral" in packet
    assert "609 to 43" in launch
    assert "276,989 to 45,281" in launch
    assert "/Users/" not in json.dumps(server)
    assert "/Users/" not in json.dumps(card)
    assert "CloudStorage" not in packet
