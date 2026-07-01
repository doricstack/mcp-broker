"""Desired-state bundle schema helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BUNDLE_SCHEMA_VERSION = 1
BUNDLE_SCHEMA_FILE = Path(__file__).resolve().parents[2] / "config" / "broker.bundle.schema.json"
BUNDLE_REQUIRED_SECTIONS = (
    "schema_version",
    "bundle_id",
    "version",
    "channel",
    "source",
    "checksum",
    "applies_to",
    "profiles",
    "upstreams",
    "clients",
    "policy",
    "compatibility",
)


def load_bundle_schema() -> dict[str, Any]:
    return json.loads(BUNDLE_SCHEMA_FILE.read_text(encoding="utf-8"))


def bundle_schema_metadata() -> dict[str, object]:
    return {
        "schema_file": str(BUNDLE_SCHEMA_FILE),
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "required_sections": BUNDLE_REQUIRED_SECTIONS,
        "executes_remote_code": False,
    }
