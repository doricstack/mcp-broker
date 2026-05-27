from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)


def _load_json(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _python_version() -> str:
    init_text = (ROOT / "src" / "mcp_broker" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__ = "([^"]+)"', init_text)
    if not match:
        raise RuntimeError("missing src/mcp_broker/__init__.py __version__")
    return match.group(1)


def main() -> int:
    expected = os.environ.get("EXPECTED_PUBLISH_VERSION", "").strip()
    ref_name = os.environ.get("GITHUB_REF_NAME", "").strip()
    if not expected and ref_name.startswith("v"):
        expected = ref_name[1:]

    versions = {
        "python": _python_version(),
        "npm": _load_json("npm/package.json")["version"],
        "mcp_registry": _load_json("registry/server.json")["version"],
        "mcp_registry_package": _load_json("registry/server.json")["packages"][0]["version"],
        "mcpb": _load_json("mcpb/manifest.json")["version"],
        "server_card_package": _load_json(".well-known/mcp/server-card.json")["packages"][0][
            "version"
        ],
    }

    if expected:
        versions["expected"] = expected

    unique_versions = sorted(set(versions.values()))
    if len(unique_versions) != 1:
        for name, version in versions.items():
            LOGGER.error("%s: %s", name, version)
        return 1

    LOGGER.info("%s", unique_versions[0])
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    raise SystemExit(main())
