from __future__ import annotations

import os
from pathlib import Path
import sys


def repo_root() -> Path:
    configured = os.environ.get("MCP_BROKER_REPO_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    for start in (Path.cwd().resolve(), Path(__file__).resolve()):
        for candidate in (start, *start.parents):
            if (candidate / "Makefile").exists() and (
                candidate / "config" / "broker.example.yaml"
            ).exists():
                return candidate
    return Path(__file__).resolve().parents[2]


def make_command(*args: str) -> list[str]:
    return [
        "make",
        *args,
        f"PYTHON={sys.executable}",
        f"PYTHON_BIN={sys.executable}",
    ]
