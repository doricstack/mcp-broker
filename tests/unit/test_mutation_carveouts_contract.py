"""The mutation gate honors the carve-out registry, and only where it should.

The gate fails on any surviving mutant, and the registry records survivors a
cross-model review adjudicated as behaviorally equivalent. Until now the two did
not speak: every carved-out survivor still failed the gate, so a release could
never pass its own mutation leg and the recorded judgment bought nothing.

Honoring the registry is only safe if it fails closed. Every test here exists
because the obvious implementation would excuse too much:

  - a row must be bound to the file's CURRENT hash, or an edit silently inherits
    the previous file's excuse
  - only a row whose reason is equivalence may excuse a survivor; a
    tool-incompatible row describes mutants that were never generated, so a
    survivor matching one is a contradiction and must not be waved through
  - a row excuses only the callables it names, not the whole file
  - the excused count is always reported, never folded into the pass
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from mcp_broker.mutation_carveouts import (
    Carveout,
    callable_of_mutant,
    excusable_survivors,
    parse_registry,
)


REGISTRY_HEADER = """# Mutation carve-outs

| ID | File and lines | Reason class | Exact candidate and explanation | Advisor sign-off |
|---|---|---|---|---|
"""


def _row(path: str, cells: str) -> str:
    return f"| `{path}` | {cells} |\n"


def _write_source(root: Path, rel: str, body: str) -> str:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return hashlib.sha256(target.read_bytes()).hexdigest()


class CallableExtraction:
    """Documented separately because the mangling is not obvious."""


def test_callable_of_mutant_strips_the_engine_prefix_and_ordinal():
    assert callable_of_mutant("src.mcp_broker.catalog.x_send_message__mutmut_4") == "send_message"


def test_callable_of_mutant_keeps_a_leading_underscore_in_the_real_name():
    # `_read_json` is mangled to `x__read_json`, so a naive lstrip of "x_"
    # would yield `read_json` and silently fail to match the registry row.
    assert callable_of_mutant("src.mcp_broker.break_glass.x__read_json__mutmut_7") == "_read_json"


def test_callable_of_mutant_returns_none_for_an_unrecognised_shape():
    assert callable_of_mutant("not-a-mutant-name") is None


def test_parse_registry_reads_path_hash_callables_and_reason(tmp_path: Path):
    registry = tmp_path / "carveouts.md"
    registry.write_text(
        REGISTRY_HEADER
        + _row(
            "src/mcp_broker/break_glass.py",
            "`_read_json` line 202, `_write_json_atomic` line 212: the `\"utf-8\"` literals "
            "| equivalent | mutmut 3.7.0; SHA-256 `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa` | signed off",
        ),
        encoding="utf-8",
    )

    rows = parse_registry(registry)

    assert len(rows) == 1
    row = rows[0]
    assert row.source_path == "src/mcp_broker/break_glass.py"
    assert row.sha256 == "a" * 64
    assert row.reason_class == "equivalent"
    # The quoted literal is not an identifier and must not become a callable.
    assert row.callables == frozenset({"_read_json", "_write_json_atomic"})


def test_parse_registry_ignores_prose_lines_and_non_source_rows(tmp_path: Path):
    registry = tmp_path / "carveouts.md"
    registry.write_text(
        REGISTRY_HEADER
        + "Some prose about the registry.\n"
        + _row("docs/not-source.md", "`x` | equivalent | SHA-256 `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb` | signed"),
        encoding="utf-8",
    )
    assert parse_registry(registry) == []


def test_a_matching_equivalent_row_excuses_only_its_named_callables(tmp_path: Path):
    digest = _write_source(tmp_path, "src/mcp_broker/break_glass.py", "x = 1\n")
    rows = [
        Carveout(
            source_path="src/mcp_broker/break_glass.py",
            sha256=digest,
            reason_class="equivalent",
            callables=frozenset({"_read_json"}),
        )
    ]
    results = [
        ("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x__read_json__mutmut_7", "survived"),
        ("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x_other__mutmut_1", "survived"),
    ]

    excused, invalid = excusable_survivors(results, rows, repo_root=tmp_path)

    assert excused == {"src.mcp_broker.break_glass.x__read_json__mutmut_7"}
    assert invalid == []


def test_a_stale_hash_excuses_nothing_and_is_reported(tmp_path: Path):
    _write_source(tmp_path, "src/mcp_broker/break_glass.py", "x = 1\n")
    rows = [
        Carveout(
            source_path="src/mcp_broker/break_glass.py",
            sha256="0" * 64,
            reason_class="equivalent",
            callables=frozenset({"_read_json"}),
        )
    ]
    results = [
        ("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x__read_json__mutmut_7", "survived"),
    ]

    excused, invalid = excusable_survivors(results, rows, repo_root=tmp_path)

    assert excused == set()
    assert len(invalid) == 1
    assert "break_glass.py" in invalid[0]
    assert "hash" in invalid[0].lower()


def test_a_missing_source_file_excuses_nothing_and_is_reported(tmp_path: Path):
    rows = [
        Carveout(
            source_path="src/mcp_broker/gone.py",
            sha256="0" * 64,
            reason_class="equivalent",
            callables=frozenset({"anything"}),
        )
    ]
    results = [("src/mcp_broker/gone.py", "src.mcp_broker.gone.x_anything__mutmut_1", "survived")]

    excused, invalid = excusable_survivors(results, rows, repo_root=tmp_path)

    assert excused == set()
    assert len(invalid) == 1
    assert "gone.py" in invalid[0]


def test_a_tool_incompatible_row_never_excuses_a_survivor(tmp_path: Path):
    """A survivor under a not-generated claim is a contradiction, not an excuse.

    The row asserts the engine produces no mutants there. If one survived, the
    row's premise is false and the right outcome is a failure that makes someone
    look, not a silent pass.
    """
    digest = _write_source(tmp_path, "src/mcp_broker/daemon.py", "y = 2\n")
    rows = [
        Carveout(
            source_path="src/mcp_broker/daemon.py",
            sha256=digest,
            reason_class="tool-incompatible",
            callables=frozenset({"serve"}),
        )
    ]
    results = [("src/mcp_broker/daemon.py", "src.mcp_broker.daemon.x_serve__mutmut_1", "survived")]

    excused, invalid = excusable_survivors(results, rows, repo_root=tmp_path)

    assert excused == set()


def test_only_survivors_are_excusable_never_a_timeout(tmp_path: Path):
    """A timeout is an unmeasured mutant, not an equivalent one.

    Equivalence is a claim about behaviour under a mutant that RAN. A timeout
    means the suite never reached a verdict, so excusing it would report a
    judgment nobody made.
    """
    digest = _write_source(tmp_path, "src/mcp_broker/break_glass.py", "x = 1\n")
    rows = [
        Carveout(
            source_path="src/mcp_broker/break_glass.py",
            sha256=digest,
            reason_class="equivalent",
            callables=frozenset({"_read_json"}),
        )
    ]
    results = [
        ("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x__read_json__mutmut_7", "timeout"),
    ]

    excused, invalid = excusable_survivors(results, rows, repo_root=tmp_path)

    assert excused == set()


def test_the_real_registry_parses_and_binds_to_real_files():
    """The shipped registry is the input this exists for, so parse it.

    A parser that only works on fixtures is the empty-scope failure: it would
    report zero problems having examined nothing real.
    """
    root = Path(__file__).resolve().parents[2]
    rows = parse_registry(root / "docs" / "mutation-carveouts.md")

    assert rows, "the shipped registry parsed to zero rows"
    equivalent = [row for row in rows if row.reason_class.startswith("equivalent")]
    assert equivalent, "no equivalence rows found in the shipped registry"
    for row in rows:
        assert (root / row.source_path).exists(), row.source_path
        assert len(row.sha256) == 64, (row.source_path, row.sha256)
