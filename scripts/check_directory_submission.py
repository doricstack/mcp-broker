from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)

REQUIRED_TOOLS = {
    "broker.search_tools",
    "broker.describe_tool",
    "broker.call_tool",
    "broker.status",
}

REQUIRED_PACKET_TERMS = [
    "mcp-broker",
    "https://github.com/NavinAgrawal/mcp-broker",
    "pipx install mcp-broker",
    "mcp-broker init",
    "mcp-broker render codex --dry-run",
    "Runtime state stays outside the repository",
    "Mutating tools require profile allowlists",
    "docs/context-reduction-measurement.md",
    "broker.search_tools",
    "broker.describe_tool",
    "broker.call_tool",
    "broker.status",
    "mcpservers.org",
    "mcp.so",
    "MCPCentral",
]

PRIVATE_MARKERS = [
    "/Users/",
    "CloudStorage",
    "config/broker.private.yaml",
    "HANDOFF",
    "SESSION_HISTORY",
]


def _submission_paths() -> dict[str, Path]:
    return {
        "packet": _repo_path("DIRECTORY_SUBMISSION_PACKET", "docs/directory-submission-packet.md"),
        "server_card": _repo_path("SERVER_CARD_PATH", ".well-known/mcp/server-card.json"),
        "registry": _repo_path("REGISTRY_METADATA_PATH", "registry/server.json"),
        "mcpb_manifest": _repo_path("MCPB_MANIFEST", "mcpb/manifest.json"),
        "launch": _repo_path("LAUNCH_DOC_PATH", "docs/launch.md"),
    }


def _repo_path(env_name: str, default: str) -> Path:
    configured = os.environ.get(env_name, default)
    path = Path(configured)
    return path if path.is_absolute() else ROOT / path


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _first_package(document: dict[str, Any], label: str, errors: list[str]) -> dict[str, Any]:
    packages = document.get("packages")
    if not isinstance(packages, list) or not packages:
        errors.append(f"{label} has no package entry")
        return {}
    package = packages[0]
    if not isinstance(package, dict):
        errors.append(f"{label} package entry is not an object")
        return {}
    return package


def _append_missing_terms(label: str, text: str, terms: list[str], errors: list[str]) -> None:
    missing = [term for term in terms if term not in text]
    for term in missing:
        errors.append(f"{label} missing required text: {term}")


def _append_private_markers(label: str, text: str, errors: list[str]) -> None:
    for marker in PRIVATE_MARKERS:
        if marker in text:
            errors.append(f"{label} contains private marker: {marker}")


def _append_missing_files(paths: dict[str, Path], errors: list[str]) -> None:
    for path in paths.values():
        if not path.is_file():
            errors.append(f"missing file: {path.relative_to(ROOT)}")


def _append_metadata_errors(
    server_card: dict[str, Any],
    registry: dict[str, Any],
    errors: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    registry_package = _first_package(registry, "registry/server.json", errors)
    card_package = _first_package(server_card, "server-card.json", errors)

    if server_card.get("name") != registry.get("name"):
        errors.append("server card name does not match registry name")
    if server_card.get("repository") != registry.get("repository", {}).get("url"):
        errors.append("server card repository does not match registry repository URL")

    expected_package = {
        "registryType": "pypi",
        "identifier": "mcp-broker",
    }
    for key, expected in expected_package.items():
        if registry_package.get(key) != expected:
            errors.append(f"registry package {key} is not {expected}")
        if card_package.get(key) != expected:
            errors.append(f"server card package {key} is not {expected}")

    if registry_package.get("transport", {}).get("type") != "stdio":
        errors.append("registry package transport is not stdio")
    if card_package.get("transport", {}).get("type") != "stdio":
        errors.append("server card package transport is not stdio")

    return registry_package, card_package


def _append_version_errors(
    registry: dict[str, Any],
    registry_package: dict[str, Any],
    card_package: dict[str, Any],
    mcpb_manifest: dict[str, Any],
    errors: list[str],
) -> None:
    versions = {
        "registry": registry.get("version"),
        "registry_package": registry_package.get("version"),
        "server_card_package": card_package.get("version"),
        "mcpb": mcpb_manifest.get("version"),
    }
    if len(set(versions.values())) != 1:
        for name, version in versions.items():
            LOGGER.error("%s version: %s", name, version)
        errors.append("metadata versions are not aligned")


def _append_mcpb_errors(mcpb_manifest: dict[str, Any], errors: list[str]) -> None:
    tool_names = {
        tool.get("name")
        for tool in mcpb_manifest.get("tools", [])
        if isinstance(tool, dict) and isinstance(tool.get("name"), str)
    }
    missing_tools = sorted(REQUIRED_TOOLS - tool_names)
    for tool in missing_tools:
        errors.append(f"mcpb manifest missing broker tool: {tool}")


def _append_document_errors(packet_text: str, launch_text: str, errors: list[str]) -> None:
    _append_missing_terms("directory submission packet", packet_text, REQUIRED_PACKET_TERMS, errors)
    _append_missing_terms(
        "launch doc",
        launch_text,
        ["609 to 43", "276,989 to 45,281", "83.65%"],
        errors,
    )


def _append_private_marker_errors(
    packet_text: str,
    launch_text: str,
    server_card: dict[str, Any],
    registry: dict[str, Any],
    mcpb_manifest: dict[str, Any],
    errors: list[str],
) -> None:
    for label, text in [
        ("directory submission packet", packet_text),
        ("launch doc", launch_text),
        ("server card", json.dumps(server_card, sort_keys=True)),
        ("registry metadata", json.dumps(registry, sort_keys=True)),
        ("mcpb manifest", json.dumps(mcpb_manifest, sort_keys=True)),
    ]:
        _append_private_markers(label, text, errors)


def _log_errors(errors: list[str]) -> int:
    for error in errors:
        LOGGER.error("%s", error)
    return 1


def main() -> int:
    paths = _submission_paths()
    errors: list[str] = []
    _append_missing_files(paths, errors)
    if errors:
        return _log_errors(errors)

    packet_text = paths["packet"].read_text(encoding="utf-8")
    launch_text = paths["launch"].read_text(encoding="utf-8")
    server_card = _load_json(paths["server_card"])
    registry = _load_json(paths["registry"])
    mcpb_manifest = _load_json(paths["mcpb_manifest"])

    registry_package, card_package = _append_metadata_errors(server_card, registry, errors)
    _append_version_errors(registry, registry_package, card_package, mcpb_manifest, errors)
    _append_mcpb_errors(mcpb_manifest, errors)
    _append_document_errors(packet_text, launch_text, errors)
    _append_private_marker_errors(
        packet_text,
        launch_text,
        server_card,
        registry,
        mcpb_manifest,
        errors,
    )

    if errors:
        return _log_errors(errors)

    LOGGER.info("Directory submission metadata is ready")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
