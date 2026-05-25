from pathlib import Path

import pytest


pytestmark = pytest.mark.journey

ROOT = Path(__file__).resolve().parents[2]
AUTH_DOC = ROOT / "docs" / "auth-recipes.md"


def test_auth_recipes_cover_supported_public_auth_patterns() -> None:
    text = AUTH_DOC.read_text(encoding="utf-8")

    required_sections = [
        "## Host Environment Variables",
        "## Runtime Secret Files",
        "## Request Metadata",
        "## OAuth And Browser Setup",
        "## Auth Repair",
        "## Status Checks",
    ]
    required_terms = [
        "env:",
        "env_files:",
        "request_meta:",
        "auth_repair:",
        "make secret-import-env SECRET_NAME=<name>",
        "broker.status",
        "auth_probe",
        "credentials_missing",
        "credentials_present",
        "auth_repair_configured",
        "auth_state",
        "auth_repair_attempts",
        "auth_repair_successes",
        "auth_repair_failures",
    ]
    private_markers = [
        "/Users/",
        "$HOME/Projects",
        "$HOME/Library",
        "$HOME/Documents",
        "CloudStorage",
    ]

    assert [section for section in required_sections if section not in text] == []
    assert [term for term in required_terms if term not in text] == []
    assert [marker for marker in private_markers if marker in text] == []


def test_readme_links_to_auth_recipes() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "[docs/auth-recipes.md](docs/auth-recipes.md)" in readme
