from __future__ import annotations

import pytest

from scripts.sync_release_metadata import _bump_version, _validate_version

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
