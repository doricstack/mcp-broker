"""The newest supported interpreter must be pinned and exercised, not merely implied.

`requires-python` declares ">=3.10" with no upper bound, so the package claims to
work on every Python from 3.10 upward. The floor half of that claim is proven by
test_python_floor_contract.py and a CI leg pinned to 3.10. The ceiling half was
proven by nothing: the main CI job tracks "3.x", which is whatever the runner
happens to ship, so the newest interpreter an operator may actually run is a
moving target that no gate names.

That gap has already cost a release gate. Thirteen assertions compared raw argparse
help text, which passes on 3.13 and fails on 3.14 because 3.14 colourizes argparse
output. The suite was green on the 3.13 worktree venv and red on the 3.14 checkout
the release is cut from. Same defect class as the 2.1.1 ImportError, at the other
end of the declared range.

So the project declares the ceiling it has actually been proven against, in one
place, and CI runs the suite there.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Without this the file sits in tests/journey but is invisible to marker-based
# selection, which is how a contract silently stops running.
pytestmark = pytest.mark.journey

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def declared_floor() -> tuple[int, int]:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'requires-python\s*=\s*">=(\d+)\.(\d+)"', text)
    assert match, "pyproject must declare a requires-python floor"
    return int(match.group(1)), int(match.group(2))


def declared_ceiling() -> tuple[int, int]:
    """The newest interpreter this project claims to have been proven against."""
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'python-ceiling\s*=\s*"(\d+)\.(\d+)"', text)
    assert match, (
        "pyproject must declare [tool.mcp-broker] python-ceiling: the newest "
        "interpreter CI proves the suite on. requires-python has no upper bound, "
        "so without this the ceiling is whatever a runner happens to ship")
    return int(match.group(1)), int(match.group(2))


def test_the_declared_ceiling_is_not_below_the_declared_floor():
    floor = declared_floor()
    ceiling = declared_ceiling()
    assert ceiling >= floor, (
        f"declared ceiling {ceiling} is below the declared floor {floor}, "
        "which claims a range no interpreter satisfies")


def test_the_ceiling_job_installs_the_resolved_version_rather_than_a_floating_one():
    """A leg tracking "3.x" proves whatever the runner shipped that day.

    The ceiling job must feed setup-python the version it resolved from pyproject,
    not "3.x" and not a second hand-written copy of the number.
    """
    declared_ceiling()  # the declaration has to exist for the job to resolve it
    ceiling_job = WORKFLOW.read_text(encoding="utf-8").split("python-ceiling:", 1)[1]
    assert "steps.ceiling.outputs.version" in ceiling_job, (
        "the ceiling job must pass its resolved version to setup-python, so the "
        "interpreter it installs is the one pyproject declares")
    assert '"3.x"' not in ceiling_job.split("dependency-floors:", 1)[0], (
        "the ceiling job must not track a floating 3.x; that is the moving target "
        "this contract exists to replace")


def test_ci_runs_the_suite_on_the_ceiling_interpreter():
    """Pinning the interpreter is not enough; the suite has to run under it."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python-ceiling:" in text, (
        "CI must carry a job named python-ceiling that runs the suite on the "
        "declared newest interpreter")
    ceiling_job = text.split("python-ceiling:", 1)[1]
    assert "make test" in ceiling_job, (
        "the python-ceiling job must run the suite, not only install the interpreter")


def test_the_ceiling_is_declared_in_exactly_one_place():
    """Two copies of a version drift the moment one is raised."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert len(re.findall(r'python-ceiling\s*=', text)) == 1, (
        "python-ceiling must be declared once in pyproject; CI reads it from there")


def test_ci_derives_the_ceiling_version_from_pyproject():
    """The workflow must read the declaration rather than carry a second copy.

    A hand-copied version is DSI-3.1: it drifts the moment pyproject is raised, and
    it fails somewhere else, later.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python-ceiling" in text and "pyproject.toml" in text, (
        "the ceiling job must resolve its version from pyproject.toml so the "
        "declaration stays single-sourced")
