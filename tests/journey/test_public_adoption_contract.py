from __future__ import annotations

import json
from pathlib import Path
import re

import pytest
import yaml

from tests.support.makefiles import read_combined_makefiles


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
        "glama.json",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/config_help.md",
        ".github/ISSUE_TEMPLATE/upstream_compatibility.md",
        ".github/pull_request_template.md",
        "docs/context-reduction-measurement.md",
        "docs/add-profile.md",
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
        "Dockerfile",
        ".dockerignore",
        "docker/docker-entrypoint.sh",
        "mcpb/manifest.json",
    ]
    missing = [path for path in required_paths if not (ROOT / path).is_file()]

    assert missing == []


def test_mcpb_manifest_tool_names_are_client_safe() -> None:
    manifest = json.loads((ROOT / "mcpb" / "manifest.json").read_text(encoding="utf-8"))
    tool_names = [tool["name"] for tool in manifest["tools"]]
    client_safe_pattern = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

    assert tool_names == [
        "broker_search_tools",
        "broker_describe_tool",
        "broker_call_tool",
        "broker_status",
    ]
    assert [name for name in tool_names if not client_safe_pattern.fullmatch(name)] == []


def test_glama_claim_metadata_is_public_safe() -> None:
    claim_path = ROOT / "glama.json"
    allowlist_path = ROOT / "public-export" / "allowlist.txt"

    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    serialized = json.dumps(claim, sort_keys=True)

    assert claim == {
        "$schema": "https://glama.ai/mcp/schemas/server.json",
        "maintainers": ["NavinAgrawal"],
    }
    if allowlist_path.exists():
        assert "glama.json" in allowlist_path.read_text(encoding="utf-8")
    assert "/Users/" not in serialized
    assert "CloudStorage" not in serialized


def test_packaged_chat_profiles_use_client_safe_broker_tool_names() -> None:
    config = yaml.safe_load((ROOT / "config" / "broker.example.yaml").read_text(encoding="utf-8"))

    assert {
        profile_name: config["profiles"][profile_name]["broker_tool_name_style"]
        for profile_name in ("codex", "claude", "gemini", "docker")
    } == {
        "codex": "snake",
        "claude": "snake",
        "gemini": "snake",
        "docker": "snake",
    }


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
        "docs/assets/quickstart-terminal.svg",
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

    assert "## 0.1.1" in changelog
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
    add_profile = (ROOT / "docs" / "add-profile.md").read_text(encoding="utf-8")
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
    required_add_profile_terms = [
        "make profile-snippet",
        "NEW_PROFILE",
        "NEW_CLIENT_FORMAT",
        "mcp-settings-json",
        "make profile-validation PROFILE=",
        "make facade-smoke PROFILE=",
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
    assert [term for term in required_add_profile_terms if term not in add_profile] == []
    assert [term for term in required_safety_terms if term not in safety] == []
    assert "docs/comparison.md" in readme
    assert "docs/add-profile.md" in readme
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
        "brew install mcp-broker",
        "docker run",
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
        "mcpb/manifest.json",
        "Smithery",
        "Glama",
        "https://glama.ai/mcp/servers/NavinAgrawal/mcp-broker",
        "PulseMCP",
        "PulseMCP has also appeared from the registry/server.json surface",
        "https://www.pulsemcp.com/servers/navinagrawal-mcp-broker",
        "Homebrew",
        "make release-gate",
        "var/quality/mutation_stats.json",
    ]
    required_publication_terms = [
        "repository description",
        "model-context-protocol",
        "pinned demo issue",
        "release notes",
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


def test_docker_packaging_contract_is_public_safe() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (ROOT / "docker" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    public_config = yaml.safe_load((ROOT / "config" / "broker.example.yaml").read_text(encoding="utf-8"))
    makefile = read_combined_makefiles(ROOT)
    allowlist_path = ROOT / "public-export" / "allowlist.txt"
    allowlist = allowlist_path.read_text(encoding="utf-8") if allowlist_path.exists() else ""

    assert "ARG PYTHON_IMAGE=python:3-slim" in dockerfile
    assert "COPY src /app/src" in dockerfile
    assert "COPY config/broker.example.yaml /app/config/broker.example.yaml" in dockerfile
    assert "ENTRYPOINT [\"/usr/local/bin/mcp-broker-docker\"]" in dockerfile
    assert "MCP_BROKER_RUNTIME_ROOT=/var/lib/mcp-broker" in dockerfile
    assert "PIP_ROOT_USER_ACTION=ignore python -m pip install" in dockerfile
    assert "mcp-broker stdio" in entrypoint
    assert "--init-if-missing" in entrypoint
    assert "MCP_BROKER_CONFIG" in entrypoint
    assert "MCP_BROKER_SOCKET" in entrypoint
    assert "${MCP_BROKER_PROFILE:-docker}" in entrypoint
    assert "docker" in public_config["profiles"]
    assert public_config["profiles"]["docker"]["compact_tools_enabled"] is True
    assert "docker-build:" in makefile
    assert "docker-smoke:" in makefile
    if allowlist:
        assert "Dockerfile" in allowlist
        assert ".dockerignore" in allowlist
        assert "docker/docker-entrypoint.sh" in allowlist
        assert "scripts/mcpb_stdio_smoke.py" in allowlist
    assert "/Users/" not in dockerfile
    assert "/Users/" not in entrypoint


def test_mcpb_manifest_contract_is_public_safe() -> None:
    manifest_path = ROOT / "mcpb" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["name"] == "mcp-broker"
    assert manifest["license"] == "MIT"
    assert manifest["author"]["name"] == "Navin B Agrawal"
    assert manifest["server"]["type"] == "binary"
    assert manifest["server"]["mcp_config"]["command"] == "${user_config.uvx_path}"
    assert manifest["server"]["mcp_config"]["args"][:2] == ["mcp-broker", "stdio"]
    assert manifest["user_config"]["uvx_path"]["default"] == "uvx"
    assert manifest["user_config"]["uvx_path"]["required"] is True
    assert "broker_call_tool" in {tool["name"] for tool in manifest["tools"]}
    assert "broker_status" in {tool["name"] for tool in manifest["tools"]}

    serialized = json.dumps(manifest, sort_keys=True)
    assert "/Users/" not in serialized
    assert "config/broker.private.yaml" not in serialized


def test_registry_template_is_public_safe_and_points_to_pypi_package() -> None:
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
    assert '"mcpServers": {' in packet
    assert '"mcp-broker": {' in packet
    assert '"command": "${user_config.uvx_path}"' in packet
    assert "UVX command path" in packet
    assert '"mcp-broker", "stdio", "--init-if-missing"' in packet
    assert "609 to 43" in launch
    assert "276,989 to 45,281" in launch
    assert "/Users/" not in json.dumps(server)
    assert "/Users/" not in json.dumps(card)
    assert "CloudStorage" not in packet


def test_directory_submission_check_is_make_backed() -> None:
    makefile = read_combined_makefiles(ROOT)
    distribution = (ROOT / "docs" / "distribution.md").read_text(encoding="utf-8")
    packet = (ROOT / "docs" / "directory-submission-packet.md").read_text(encoding="utf-8")
    script = ROOT / "scripts" / "check_directory_submission.py"
    script_text = script.read_text(encoding="utf-8") if script.exists() else ""

    assert script.is_file()
    assert "directory-submission-check:" in makefile
    assert "$(PYTHON_BIN) \"$(ROOT)/scripts/check_directory_submission.py\"" in makefile
    assert "make directory-submission-check" in distribution
    assert "/Users/" not in script_text
    for term in [
        "broker_search_tools",
        "broker_describe_tool",
        "broker_call_tool",
        "broker_status",
        "https://github.com/NavinAgrawal/mcp-broker",
        "docs/context-reduction-measurement.md",
        "https://glama.ai/",
        "https://glama.ai/mcp/servers/NavinAgrawal/mcp-broker",
        "glama.json",
        "https://www.pulsemcp.com/submit",
        "https://www.pulsemcp.com/servers/navinagrawal-mcp-broker",
        "PulseMCP: listed at",
        "mcpservers.org: approved",
        "https://mcpservers.org/servers/navinagrawal/mcp-broker",
        "mcp.so: submitted",
        "It requires Sign In",
        "`registry.mcpcentral.io` currently does not resolve",
        "blocks non-browser automation",
        "mcp-publisher login github --registry https://registry.mcpcentral.io",
        "https://github.com/punkpeye/awesome-mcp-servers/pull/6993",
        "https://github.com/appcypher/awesome-mcp-servers/compare/main...NavinAgrawal:awesome-mcp-servers-1:add-mcp-broker",
        "Server tab",
        "Connector tab",
        "Settings -> Extensions -> Advanced settings -> Extension Developer -> Install Extension",
        "make smithery-payload-check",
        "make smithery-publish",
        "make mcpb-stdio-smoke",
        "scripts/mcpb_stdio_smoke.py",
        "scripts/smithery_release.py",
        "server.mcpb",
    ]:
        assert term in packet
