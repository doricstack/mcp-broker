from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

ZERO_CHECKSUM = "0" * 64


def minimal_bundle() -> dict[str, object]:
    return {
        "schema_version": 1,
        "bundle_id": "personal-local",
        "version": "2026.07.01",
        "channel": "stable",
        "source": {
            "type": "file",
            "uri": "file:///tmp/mcp-broker/bundles/personal-local.json",
            "created_by": "mcp-broker",
        },
        "checksum": {
            "algorithm": "sha256",
            "value": ZERO_CHECKSUM,
        },
        "applies_to": {
            "broker_id": "mcp-broker-local",
            "environments": ["local"],
        },
        "profiles": {
            "codex": {
                "max_tools": 80,
                "compact_tools_enabled": True,
                "broker_tool_name_style": "snake",
            },
        },
        "upstreams": {
            "catalog-cache": {
                "enabled": True,
                "mode": "shared",
                "transport": "stdio",
                "command": "catalog-cache-server",
                "profiles": ["codex"],
            },
        },
        "clients": {
            "codex": {
                "format": "codex-toml",
                "entry_name": "mcp-broker",
            },
        },
        "policy": {
            "approval_required": True,
            "allow_remote_code_execution": False,
            "mutating_upstreams_require_allowlist": True,
        },
        "compatibility": {
            "min_config_schema_version": 1,
            "max_config_schema_version": 1,
            "required_features": ["broker.identity"],
        },
    }


def signed_bundle(bundle: dict[str, object] | None = None) -> dict[str, object]:
    signed = copy.deepcopy(bundle or minimal_bundle())
    signed["checksum"]["value"] = ZERO_CHECKSUM
    signed["checksum"]["value"] = checksum_for_bundle(signed)
    return signed


def write_signed_bundle(path: Path, bundle: dict[str, object] | None = None) -> Path:
    path.write_text(json.dumps(signed_bundle(bundle), indent=2, sort_keys=True), encoding="utf-8")
    return path


def checksum_for_bundle(bundle: dict[str, object]) -> str:
    normalized = copy.deepcopy(bundle)
    normalized["checksum"]["value"] = ZERO_CHECKSUM
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
