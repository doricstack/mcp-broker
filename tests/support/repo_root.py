"""Locate the repository a contract is describing.

Counting parents from __file__ is right only when the file sits in the repo.
Mutation runs every collected test from mutmut's own partial copy at
<repo>/mutants, which setup.cfg's also_copy populates with public-export and the
makefiles but not with var, .test-impact.json or setup.cfg itself. A contract
that counts parents therefore describes that copy and reports repo-root files
missing from a repository that has them.

The nearest ancestor holding the allowlist is therefore the right answer, except
that mutmut's copy holds one too. Skipping that copy is what separates the two:
picking the outermost match instead would walk out of a git worktree and into the
primary checkout, which holds an allowlist as well and sits at a different commit.

Public exports omit public-export entirely. Only after exhausting allowlist
matches, fall back to pyproject.toml so exported contracts can locate their root.
Both passes skip mutmut's partial copy.
"""
from __future__ import annotations

from pathlib import Path

ALLOWLIST_RELATIVE_PATH = Path("public-export") / "allowlist.txt"
MUTANTS_DIRECTORY_NAME = "mutants"


def repo_root_for(start: Path) -> Path:
    """Prefer the export allowlist, then the nearest pyproject.toml ancestor.

    mutmut's partial copy is skipped, since it carries a copy of that allowlist
    but not the rest of the repository the allowlist describes.
    """
    for candidate in start.resolve().parents:
        if candidate.name == MUTANTS_DIRECTORY_NAME:
            continue
        if (candidate / ALLOWLIST_RELATIVE_PATH).is_file():
            return candidate
    for candidate in start.resolve().parents:
        if candidate.name == MUTANTS_DIRECTORY_NAME:
            continue
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError(
        f"no ancestor of {start} holds {ALLOWLIST_RELATIVE_PATH} or pyproject.toml")
