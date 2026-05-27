#!/usr/bin/env python3
"""Update the Homebrew tap formula from the published PyPI sdist."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import sys
from typing import Any, Sequence
from urllib.request import urlopen


LOGGER = logging.getLogger("update_homebrew_formula")


@dataclass(frozen=True)
class FormulaUpdate:
    url: str
    sha256: str


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        update = find_sdist_release(fetch_pypi_release(args.project, args.version))
        before = args.formula.read_text(encoding="utf-8")
        after = render_formula_update(before, update)
        changed = before != after
        if changed:
            args.formula.write_text(after, encoding="utf-8")
        sys.stdout.write(
            json.dumps(
                {
                    "changed": changed,
                    "formula": str(args.formula),
                    "sha256": update.sha256,
                    "url": update.url,
                    "version": args.version,
                },
                sort_keys=True,
            )
            + "\n"
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        LOGGER.error("Homebrew formula update failed: %s", exc)
        return 2


def fetch_pypi_release(project: str, version: str) -> dict[str, Any]:
    url = f"https://pypi.org/pypi/{project}/{version}/json"
    with urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def find_sdist_release(payload: dict[str, Any]) -> FormulaUpdate:
    for release in payload.get("urls", []):
        if release.get("packagetype") != "sdist":
            continue
        url = release["url"]
        sha256 = release["digests"]["sha256"]
        if not isinstance(url, str) or not isinstance(sha256, str):
            raise ValueError("PyPI sdist URL and sha256 must be strings")
        return FormulaUpdate(url=url, sha256=sha256)
    raise ValueError("PyPI release payload does not contain an sdist")


def render_formula_update(text: str, update: FormulaUpdate) -> str:
    text, url_count = re.subn(
        r'(^\s*url\s+")([^"]*mcp_broker-[^"]+\.tar\.gz)(")',
        rf"\g<1>{update.url}\g<3>",
        text,
        count=1,
        flags=re.M,
    )
    if url_count != 1:
        raise ValueError("formula url line for mcp_broker sdist was not found")

    text, sha_count = re.subn(
        r'(^\s*sha256\s+")([^"]+)(")',
        rf"\g<1>{update.sha256}\g<3>",
        text,
        count=1,
        flags=re.M,
    )
    if sha_count != 1:
        raise ValueError("formula sha256 line was not found")
    return text


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--formula", type=Path, required=True, help="Formula file to update")
    parser.add_argument("--project", default="mcp-broker", help="PyPI project name")
    parser.add_argument("--version", required=True, help="PyPI version to read")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
