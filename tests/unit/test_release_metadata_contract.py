from __future__ import annotations

import subprocess
import sys

import pytest

from scripts.sync_release_metadata import (
    _bump_version,
    _validate_version,
    docker_catalog_version_from_text,
    replace_docker_catalog_version,
)

pytestmark = pytest.mark.unit


def test_release_bump_calculates_patch_minor_and_major_versions() -> None:
    assert _bump_version("2.3.4", "patch") == "2.3.5"
    assert _bump_version("2.3.4", "minor") == "2.4.0"
    assert _bump_version("2.3.4", "major") == "3.0.0"


def test_release_version_validation_rejects_non_semver() -> None:
    assert _validate_version("2.3.4") == "2.3.4"

    try:
        _validate_version("v2.3.4")
    except ValueError as exc:
        assert "invalid semantic version" in str(exc)
    else:
        raise AssertionError("version validation accepted v-prefixed input")


def test_emit_version_only_does_not_report_synchronization() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/sync_release_metadata.py",
            "--version",
            "9.8.7",
            "--emit-version",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "9.8.7\n"
    assert result.stderr == ""


def test_docker_catalog_version_sync_uses_standard_library_parser() -> None:
    text = "name: mcp-broker\nimage: docker.io/navinagrawal/mcp-broker:2.3.4\ncategory: dev\n"

    updated = replace_docker_catalog_version(text, "2.3.5")

    assert docker_catalog_version_from_text(updated) == "2.3.5"
    assert updated == (
        "name: mcp-broker\n"
        "image: docker.io/navinagrawal/mcp-broker:2.3.5\n"
        "category: dev\n"
    )
