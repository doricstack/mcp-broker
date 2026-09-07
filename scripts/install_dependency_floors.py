#!/usr/bin/env python3
"""Install each runtime dependency at the lowest version pyproject permits.

pyproject is the single source of truth for what a user may install. Listing the
floor versions again in a workflow would duplicate that and go stale the moment a
floor moves, so they are derived here instead.

Exits non-zero when a dependency is not a simple `>=` floor, because silently
skipping one would leave it unproven while the job still reported success.
"""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
import tomllib
from pathlib import Path

LOGGER = logging.getLogger(__name__)

FLOOR = re.compile(r"([A-Za-z0-9_.-]+)\s*>=\s*([0-9][0-9A-Za-z.+-]*)$")


class UnpinnableDependency(RuntimeError):
    """A declared dependency whose floor cannot be determined."""


def declared_floors(pyproject: Path) -> list[tuple[str, str]]:
    payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    dependencies = payload.get("project", {}).get("dependencies") or []
    if not dependencies:
        raise UnpinnableDependency("no runtime dependencies declared; nothing to pin")
    floors: list[tuple[str, str]] = []
    for entry in dependencies:
        match = FLOOR.fullmatch(entry.strip())
        if not match:
            raise UnpinnableDependency(
                f"dependency {entry!r} is not a simple '>=' floor; "
                "extend this script rather than leaving it unproven")
        floors.append((match.group(1), match.group(2)))
    return floors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pyproject", default=Path("pyproject.toml"), type=Path)
    parser.add_argument("--pip", required=True, help="pip executable to install with")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    # Report on stdout so a caller can read the resolved pins, and keep the
    # message format bare so the pins are the whole line.
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)

    try:
        floors = declared_floors(args.pyproject)
    except UnpinnableDependency as error:
        LOGGER.error("%s", error)
        return 2

    pins = [f"{name}=={version}" for name, version in floors]
    LOGGER.info("declared dependency floors: %s", " ".join(pins))
    if args.dry_run:
        return 0
    return subprocess.run([str(args.pip), "install", "--quiet", *pins], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
