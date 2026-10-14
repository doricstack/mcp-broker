"""Repository discovery must work in exported, worktree and mutation checkouts.

This contract lives in the exported suite, not in the private one, because the
case that broke was the public checkout: the export deliberately leaves
public-export/ behind, so the allowlist marker is absent there and collection
aborted before a single test ran.
"""

from pathlib import Path

import pytest

from tests.support.repo_root import repo_root_for

pytestmark = pytest.mark.unit


def test_public_checkout_without_an_allowlist_resolves_to_its_pyproject(tmp_path: Path) -> None:
    """The export copies the allowlist's matches, never the allowlist itself."""
    root = tmp_path / "public"
    root.mkdir()
    (root / "pyproject.toml").touch()

    assert repo_root_for(root / "tests" / "test_contract.py") == root


def test_the_mutation_copy_is_skipped_for_the_pyproject_fallback_too(tmp_path: Path) -> None:
    """mutmut's copy carries a pyproject of its own, and describes no repository."""
    root = tmp_path / "public"
    root.mkdir()
    (root / "pyproject.toml").touch()
    copy = root / "mutants"
    copy.mkdir()
    (copy / "pyproject.toml").touch()

    assert repo_root_for(copy / "tests" / "test_contract.py") == root


def test_allowlist_is_preferred_over_nearer_pyproject(tmp_path: Path) -> None:
    """The two markers are searched in turn, not merged into one walk."""
    (tmp_path / "public-export").mkdir()
    (tmp_path / "public-export" / "allowlist.txt").touch()
    inner = tmp_path / "nested"
    inner.mkdir()
    (inner / "pyproject.toml").touch()

    assert repo_root_for(inner / "tests" / "test_contract.py") == tmp_path


def test_a_nested_checkout_wins_over_the_one_that_contains_it(tmp_path: Path) -> None:
    """This repository is worked in git worktrees, and both hold an allowlist.

    Resolving to the outermost match would describe the primary checkout, which
    sits at a different commit.
    """
    outer = tmp_path / "outer"
    (outer / "public-export").mkdir(parents=True)
    (outer / "public-export" / "allowlist.txt").write_text("mk/**\n", encoding="utf-8")

    inner = outer / "worktrees" / "feature"
    (inner / "public-export").mkdir(parents=True)
    (inner / "public-export" / "allowlist.txt").write_text("mk/**\n", encoding="utf-8")

    assert repo_root_for(inner / "tests" / "test_contract.py") == inner
