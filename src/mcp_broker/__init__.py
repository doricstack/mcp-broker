"""mcp-broker package."""

from __future__ import annotations

import json
import os
from importlib import metadata
from pathlib import Path

__all__ = ["__version__"]


def _source_tree_version() -> str:
    package_json = Path(__file__).resolve().parents[2] / "npm" / "package.json"
    try:
        return str(json.loads(package_json.read_text(encoding="utf-8"))["version"])
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("MCP_BROKER_VERSION is required outside installed packages") from exc


def _resolve_version() -> str:
    env_version = os.environ.get("MCP_BROKER_VERSION", "").strip()
    if env_version:
        return env_version
    try:
        return metadata.version("mcp-broker")
    except metadata.PackageNotFoundError:
        return _source_tree_version()


__version__ = _resolve_version()
