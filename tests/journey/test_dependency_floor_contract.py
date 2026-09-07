"""The declared dependency floors must be exercised, not just declared.

pyproject allows `jsonschema>=4.25.1`, so that is what a user is permitted to
install, but every ordinary suite run resolves the newest version instead. The
lower bound is therefore never executed. This is the same shape as the defect that
broke published 2.1.1: `requires-python` allowed 3.10 while nothing ever imported
the package on 3.10, so a 3.11-only name shipped.

A floor is either proven or it is not offered.

These tests deliberately assert the mechanism rather than the version numbers.
Naming `jsonschema==4.25.1` here would copy pyproject into a second place and go
stale the moment a floor moves, which is the defect that already had to be
removed from the distribution contract.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.journey

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
INSTALLER = ROOT / "scripts" / "install_dependency_floors.py"


def declared_floors() -> dict[str, str]:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    floors: dict[str, str] = {}
    for entry in payload["project"]["dependencies"]:
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*>=\s*([0-9][0-9A-Za-z.+-]*)", entry.strip())
        assert match, f"dependency {entry!r} is not a simple >= floor; extend the installer"
        floors[match.group(1)] = match.group(2)
    assert floors, "no runtime dependencies found to check"
    return floors


def test_every_runtime_dependency_declares_a_lower_bound() -> None:
    """An unbounded dependency lets a user resolve a version nobody has tried."""
    floors = declared_floors()
    assert all(version for version in floors.values())
    assert len(floors) >= 2, "expected at least the two known runtime dependencies"


def test_the_installer_derives_every_floor_from_pyproject() -> None:
    """The installer must report exactly pyproject's floors, deriving not copying."""
    result = subprocess.run(
        [sys.executable, str(INSTALLER), "--pyproject", str(ROOT / "pyproject.toml"),
         "--pip", "/nonexistent-pip-not-used-in-dry-run", "--dry-run"],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert result.returncode == 0, result.stderr
    reported = set(result.stdout.split("floors:", 1)[1].split())
    expected = {f"{name}=={version}" for name, version in declared_floors().items()}
    assert reported == expected, (
        f"installer reported {sorted(reported)}, pyproject declares {sorted(expected)}")


def test_the_installer_refuses_a_dependency_it_cannot_pin(tmp_path: Path) -> None:
    """Skipping an unpinnable dependency would leave it unproven under a green job."""
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[project]\nname = "x"\nversion = "0"\ndependencies = ["something-else"]\n',
        encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(INSTALLER), "--pyproject", str(project),
         "--pip", "/nonexistent-pip-not-used-in-dry-run", "--dry-run"],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT))
    assert result.returncode != 0
    # The script logs to stdout so a caller can read the resolved pins; the
    # refusal has to be findable wherever it lands.
    assert "not a simple" in result.stdout + result.stderr


def test_ci_has_a_job_that_proves_the_floors_through_make() -> None:
    """The floors must be installed and the suite then run, both via Make."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "dependency-floors:" in workflow, (
        "ci.yml has no dependency-floors job; the declared lower bounds are never run")
    body = workflow.split("dependency-floors:", 1)[1]
    assert "make deps-floor" in body, (
        "the dependency-floors job never installs the declared floors")
    assert "make test" in body, (
        "the dependency-floors job installs the floors but never runs the suite")


def test_the_floor_job_uses_the_declared_python_floor() -> None:
    """Proving the dependency floors on a newer interpreter tests a mix nobody ships."""
    payload = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', payload)
    assert match, "pyproject must declare a requires-python floor"
    body = WORKFLOW.read_text(encoding="utf-8").split("dependency-floors:", 1)[1]
    assert f'python-version: "{match.group(1)}"' in body, (
        f"the dependency-floors job must run on Python {match.group(1)}, the declared floor")


def test_make_exposes_the_floor_target() -> None:
    """A workflow calling a target that does not exist fails only in CI."""
    combined = "".join(
        path.read_text(encoding="utf-8")
        for path in [ROOT / "Makefile", *sorted((ROOT / "mk").glob("*.mk"))])
    assert "deps-floor:" in combined, "make has no deps-floor target for CI to call"
    assert "install_dependency_floors.py" in combined, (
        "deps-floor must run the installer that derives floors from pyproject")
