from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.support.makefiles import (
    expand_make_value,
    read_combined_makefiles,
    read_make_variable_defaults,
)


pytestmark = pytest.mark.journey

ROOT = Path(__file__).resolve().parents[2]


def test_codex_plugin_manifest_is_public_safe_and_matches_package_metadata() -> None:
    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    make_vars = read_make_variable_defaults(ROOT)
    package = json.loads((ROOT / "npm" / "package.json").read_text(encoding="utf-8"))
    repository_url = expand_make_value(make_vars, make_vars["GITHUB_REPOSITORY_URL"])

    assert manifest["name"] == expand_make_value(make_vars, make_vars["PACKAGE_SLUG"])
    assert manifest["version"] == package["version"]
    assert manifest["repository"] == repository_url
    assert manifest["homepage"] == repository_url
    assert manifest["license"] == "MIT"
    assert manifest["author"] == {"name": "mcp-broker maintainers"}
    assert {"hooks", "apps", "mcpServers"} & set(manifest) == set()

    interface = manifest["interface"]
    assert interface["displayName"] == "mcp-broker"
    assert interface["developerName"] == "mcp-broker maintainers"
    assert interface["category"] == "Productivity"
    assert interface["capabilities"] == ["Interactive", "Write"]
    assert 1 <= len(interface["defaultPrompt"]) <= 3
    assert [prompt for prompt in interface["defaultPrompt"] if len(prompt) > 128] == []

    serialized = json.dumps(manifest, sort_keys=True)
    forbidden_terms = [
        "/Users/",
        "CloudStorage",
        "broker.private.yaml",
        "navin@",
        "ms365-",
        "codebase-memory",
    ]
    assert [term for term in forbidden_terms if term in serialized] == []


def test_plugin_make_targets_are_approval_gated_and_package_owned() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    combined = read_combined_makefiles(ROOT)
    make_vars = read_make_variable_defaults(ROOT)

    assert "include $(ROOT)/mk/plugin.mk" in makefile
    assert make_vars["PLUGIN_CLIENT"] == "codex"
    assert make_vars["PLUGIN_APPLY"] == "0"
    for target in [
        "plugin-install",
        "plugin-status",
        "plugin-render",
        "plugin-apply",
        "plugin-rollback",
    ]:
        assert f"{target}:" in combined
        assert f"{target}: " in combined

    required_delegations = [
        "$(MAKE) --no-print-directory setup",
        "$(MAKE) --no-print-directory broker-status",
        "$(MAKE) --no-print-directory config-render",
        "$(MAKE) --no-print-directory config-rollback",
    ]
    assert [term for term in required_delegations if term not in combined] == []
    assert "CONFIG_RENDER_APPLY=0" in combined
    assert "CONFIG_RENDER_APPLY=1" in combined
    assert '[[ "$(PLUGIN_APPLY)" == "1" ]]' in combined
    assert "PLUGIN_APPLY=1 is required for plugin rollback" in combined
    assert "/Users/" not in combined
    assert "CloudStorage" not in combined


def test_plugin_setup_docs_describe_generic_safe_flow() -> None:
    docs = (ROOT / "docs" / "plugin-setup.md").read_text(encoding="utf-8")
    required_terms = [
        "make plugin-install",
        "make plugin-status",
        "make plugin-render",
        "make plugin-apply PLUGIN_APPLY=1",
        "make plugin-rollback PLUGIN_APPLY=1",
        "CONFIG_RENDER_APPLY=0",
        "No client config is written unless",
        ".codex-plugin/plugin.json",
    ]
    forbidden_terms = [
        "/Users/",
        "CloudStorage",
        "broker.private.yaml",
        "navin@",
        "ms365-",
        "codebase-memory",
    ]

    assert [term for term in required_terms if term not in docs] == []
    assert [term for term in forbidden_terms if term in docs] == []
