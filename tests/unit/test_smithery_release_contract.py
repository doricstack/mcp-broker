import json
import zipfile
from pathlib import Path

import pytest

from scripts.smithery_release import build_payload_from_manifest, load_mcpb_manifest


pytestmark = pytest.mark.unit


def test_smithery_payload_adds_tool_input_schemas_without_changing_mcpb_manifest(
    tmp_path: Path,
) -> None:
    manifest = {
        "name": "mcp-broker",
        "version": "1.1.0",
        "server": {"type": "binary", "mcp_config": {"command": "uvx"}},
        "tools": [
            {"name": "broker.status", "description": "Report broker health."},
            {
                "name": "broker.call_tool",
                "description": "Call one upstream tool.",
                "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}},
            },
        ],
        "user_config": {},
    }

    bundle_path = tmp_path / "server.mcpb"
    with zipfile.ZipFile(bundle_path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))

    loaded = load_mcpb_manifest(bundle_path)
    payload = build_payload_from_manifest(loaded)

    assert loaded["tools"][0] == {"name": "broker.status", "description": "Report broker health."}
    assert payload["type"] == "stdio"
    assert payload["runtime"] == "binary"
    assert payload["serverCard"]["tools"] == [
        {
            "name": "broker.status",
            "description": "Report broker health.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "broker.call_tool",
            "description": "Call one upstream tool.",
            "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    ]


def test_smithery_payload_converts_mcpb_user_config_to_json_schema() -> None:
    manifest = {
        "name": "mcp-broker",
        "version": "1.1.0",
        "server": {"type": "binary", "mcp_config": {"command": "${user_config.uvx_path}"}},
        "tools": [],
        "user_config": {
            "uvx_path": {
                "type": "string",
                "title": "UVX command path",
                "description": "Command or absolute path for uvx.",
                "required": True,
                "default": "uvx",
            },
            "runtime_root": {
                "type": "directory",
                "title": "Runtime directory",
                "required": True,
                "default": "${HOME}/mcp/mcp-broker",
            },
            "config_path": {
                "type": "file",
                "title": "Config path",
                "required": False,
                "default": "${HOME}/mcp/mcp-broker/config/broker.yaml",
            },
        },
    }

    payload = build_payload_from_manifest(manifest)

    assert payload["configSchema"] == {
        "type": "object",
        "properties": {
            "uvx_path": {
                "type": "string",
                "title": "UVX command path",
                "description": "Command or absolute path for uvx.",
                "default": "uvx",
            },
            "runtime_root": {
                "type": "string",
                "title": "Runtime directory",
                "default": "${HOME}/mcp/mcp-broker",
            },
            "config_path": {
                "type": "string",
                "title": "Config path",
                "default": "${HOME}/mcp/mcp-broker/config/broker.yaml",
            },
        },
        "required": ["uvx_path", "runtime_root"],
    }


def test_smithery_release_adapter_does_not_depend_on_transitive_requests() -> None:
    script = Path("scripts/smithery_release.py").read_text(encoding="utf-8")

    assert "import requests" not in script
    assert "urllib.request" in script
