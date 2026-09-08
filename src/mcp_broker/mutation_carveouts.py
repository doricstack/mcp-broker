"""Read the carve-out registry so the mutation gate can honor adjudicated equivalents.

The gate fails on any surviving mutant. The registry records survivors that a
review adjudicated as behaviorally equivalent, each bound to the source file's
SHA-256 at the time of that review. Without this module the two never met, so a
release could not pass its own mutation leg and the recorded judgment bought
nothing.

Every rule here exists to make the excuse narrower than the registry row looks:

- A row excuses nothing unless the file's CURRENT hash equals the recorded one.
  The hash is the whole basis of the claim; once the file changes, the review was
  of different code and inheriting its verdict is how a real defect gets waved
  through.
- Only an equivalence row may excuse a survivor. A tool-incompatible row asserts
  the engine generates no mutants there, so a survivor matching one falsifies the
  row's premise and must fail loudly rather than pass quietly.
- A row excuses only the callables it names, never the rest of the file.
- Only a survivor is excusable. A timeout is a mutant that never reached a
  verdict, and equivalence is a claim about behaviour under a mutant that ran.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


# The engine mangles `def name(...)` into `x_name__mutmut_<ordinal>`, so a
# leading-underscore callable becomes `x__name`. Capture everything between the
# prefix and the ordinal rather than stripping a fixed number of characters.
MUTANT_NAME_RE = re.compile(r"\.x_(?P<callable>.+?)__mutmut_\d+$")
# Identifiers only. The description cells also carry backticked non-identifiers
# such as `"utf-8"`, and treating those as callable names would widen the excuse.
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SOURCE_ROW_RE = re.compile(r"^\|\s*`(?P<path>src/[^`]+\.py)`\s*\|")
SHA256_RE = re.compile(r"SHA-256\s+`(?P<digest>[0-9a-f]{64})`")


@dataclass(frozen=True)
class Carveout:
    source_path: str
    sha256: str
    reason_class: str
    callables: frozenset[str]

    @property
    def is_equivalence(self) -> bool:
        """Only an equivalence claim can excuse a mutant that ran and survived."""
        return self.reason_class.startswith("equivalent")


def callable_of_mutant(mutant_name: str) -> str | None:
    """The callable a mutant belongs to, or None if the name is not a mutant."""
    match = MUTANT_NAME_RE.search(mutant_name)
    if match is None:
        return None
    return match.group("callable")


def parse_registry(path: Path) -> list[Carveout]:
    """Rows of the registry that name a source file under src/.

    Anything else in the document is prose or a non-source row and is skipped.
    A row without a 64-character SHA-256 is skipped too: an unbound row cannot be
    verified, so it must not be able to excuse anything.
    """
    if not path.exists():
        return []

    rows: list[Carveout] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row_match = SOURCE_ROW_RE.match(line)
        if row_match is None:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        # cells[0] is the empty string before the leading pipe.
        if len(cells) < 5:
            continue
        description, reason = cells[2], cells[3]
        digest_match = SHA256_RE.search(line)
        if digest_match is None:
            continue
        callables = frozenset(
            token
            for token in re.findall(r"`([^`]+)`", description)
            if IDENTIFIER_RE.match(token)
        )
        rows.append(
            Carveout(
                source_path=row_match.group("path"),
                sha256=digest_match.group("digest"),
                reason_class=reason,
                callables=callables,
            )
        )
    return rows


def excusable_survivors(
    results: list[tuple[str, str, str]],
    carveouts: list[Carveout],
    *,
    repo_root: Path,
) -> tuple[set[str], list[str]]:
    """Which surviving mutants the registry excuses, and which rows are unusable.

    Returns the set of excused mutant names and a list of human-readable problems
    with rows that could not be applied. An unusable row excuses nothing; it is
    reported so a stale registry is visible rather than silently permissive.
    """
    by_path: dict[str, list[Carveout]] = {}
    for row in carveouts:
        by_path.setdefault(row.source_path, []).append(row)

    verified: dict[str, list[Carveout]] = {}
    invalid: list[str] = []
    for source_path, rows in sorted(by_path.items()):
        target = repo_root / source_path
        if not target.exists():
            invalid.append(f"{source_path}: carve-out names a file that does not exist")
            continue
        current = hashlib.sha256(target.read_bytes()).hexdigest()
        matching = [row for row in rows if row.sha256 == current]
        stale = [row for row in rows if row.sha256 != current]
        if stale:
            invalid.append(
                f"{source_path}: {len(stale)} carve-out row(s) bound to a different "
                f"source hash than the file's current {current[:12]}; they excuse nothing"
            )
        if matching:
            verified[source_path] = matching

    excused: set[str] = set()
    for source_path, mutant_name, status in results:
        if status != "survived":
            continue
        rows = verified.get(source_path)
        if not rows:
            continue
        name = callable_of_mutant(mutant_name)
        if name is None:
            continue
        for row in rows:
            if row.is_equivalence and name in row.callables:
                excused.add(mutant_name)
                break
    return excused, invalid
