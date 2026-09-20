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

pytestmark = pytest.mark.unit

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


def test_parse_registry_returns_nothing_when_the_registry_is_absent(tmp_path: Path):
    """A missing registry excuses nothing, and says so by returning nothing.

    Raising here would surface as a mutation-gate failure, which reads as
    mutants misbehaving rather than as a registry that is not there. Excusing
    nothing is the same answer either way, and the gate reports it as such.
    """
    assert parse_registry(tmp_path / "absent.md") == []


def test_parse_registry_skips_a_truncated_row(tmp_path: Path):
    """A row too short to carry a reason class and a sign-off cannot be applied.

    Reading whatever cells happen to be present would let a half-written row
    contribute a callable set with no recorded judgment behind it.
    """
    registry = tmp_path / "carveouts.md"
    registry.write_text(
        REGISTRY_HEADER + "| `src/mcp_broker/break_glass.py` | `_read_json` only |\n",
        encoding="utf-8",
    )

    assert parse_registry(registry) == []


def test_parse_registry_skips_a_source_row_without_a_sha256(tmp_path: Path):
    """An unbound row cannot be verified, so it must not be able to excuse.

    The digest is what ties a judgment to the code it was made about. Without
    it the row would inherit an old verdict onto source that may have moved.
    """
    registry = tmp_path / "carveouts.md"
    registry.write_text(
        REGISTRY_HEADER
        + _row(
            "src/mcp_broker/break_glass.py",
            "`_read_json` | equivalent | no digest recorded here | signed off",
        ),
        encoding="utf-8",
    )

    assert parse_registry(registry) == []


def test_a_survivor_the_engine_did_not_name_is_never_excused(tmp_path: Path):
    """A result line with no mutant ordinal has no callable to attribute.

    Only a name the engine mangled identifies which callable a survivor came
    from. Anything else cannot be matched against a row's callables, and
    guessing at one would excuse a result the registry never judged.
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
    results = [("src/mcp_broker/break_glass.py", "not-a-mutant-name", "survived")]

    excused, invalid = excusable_survivors(results, rows, repo_root=tmp_path)

    assert excused == set()
    assert invalid == []


def test_the_real_registry_parses_and_binds_to_real_files():
    """Historical and pending evidence must not excuse current mutants."""
    from mcp_broker.mutation_scope import load_whole_file_carveouts

    root = Path(__file__).resolve().parents[2]
    registry = root / "docs" / "mutation-carveouts.md"
    assert "> | `src/mcp_broker/daemon.py` |" in registry.read_text(encoding="utf-8")
    assert parse_registry(registry) == []
    assert load_whole_file_carveouts(registry) == set()


def test_parse_registry_accepts_a_row_without_a_trailing_pipe(tmp_path: Path):
    """A five-cell row is a row: four fields plus the empty cell before the pipe.

    Only a row that cannot carry a reason and a digest belongs in the skip.
    """
    registry = tmp_path / "carveouts.md"
    registry.write_text(
        REGISTRY_HEADER
        + "| `src/mcp_broker/sample.py` | `func`: the encoding literal | equivalent "
        + f"| mutmut 3.7.0; SHA-256 `{'a' * 64}`\n",
        encoding="utf-8",
    )

    rows = parse_registry(registry)

    assert len(rows) == 1
    assert rows[0].source_path == "src/mcp_broker/sample.py"
    assert rows[0].callables == frozenset({"func"})


def test_parse_registry_keeps_reading_after_a_prose_line(tmp_path: Path):
    """A line that is not a source row is skipped, not a reason to stop."""
    registry = tmp_path / "carveouts.md"
    registry.write_text(
        REGISTRY_HEADER
        + "Prose between the header and the rows.\n"
        + _row(
            "src/mcp_broker/sample.py",
            f"`func` | equivalent | mutmut 3.7.0; SHA-256 `{'a' * 64}` | signed",
        ),
        encoding="utf-8",
    )

    rows = parse_registry(registry)

    assert [row.source_path for row in rows] == ["src/mcp_broker/sample.py"]


def test_parse_registry_keeps_reading_after_a_row_without_a_sha256(tmp_path: Path):
    """An unbound row is skipped; the rows below it are still rows."""
    registry = tmp_path / "carveouts.md"
    registry.write_text(
        REGISTRY_HEADER
        + _row(
            "src/mcp_broker/unbound.py",
            "`func` | equivalent | no digest recorded here | signed off",
        )
        + _row(
            "src/mcp_broker/sample.py",
            f"`func` | equivalent | mutmut 3.7.0; SHA-256 `{'a' * 64}` | signed",
        ),
        encoding="utf-8",
    )

    rows = parse_registry(registry)

    assert [row.source_path for row in rows] == ["src/mcp_broker/sample.py"]


def test_parse_registry_keeps_reading_after_a_truncated_row(tmp_path: Path):
    """A row too short to carry a reason is skipped, not a reason to stop."""
    registry = tmp_path / "carveouts.md"
    registry.write_text(
        REGISTRY_HEADER
        + "| `src/mcp_broker/truncated.py` | only two cells\n"
        + _row(
            "src/mcp_broker/sample.py",
            f"`func` | equivalent | mutmut 3.7.0; SHA-256 `{'a' * 64}` | signed",
        ),
        encoding="utf-8",
    )

    rows = parse_registry(registry)

    assert [row.source_path for row in rows] == ["src/mcp_broker/sample.py"]


def test_a_missing_source_does_not_stop_the_other_rows_being_verified(tmp_path: Path):
    """One unusable row is reported; it does not abandon the rows after it."""
    digest = _write_source(tmp_path, "src/mcp_broker/sample.py", "x = 1\n")
    rows = [
        Carveout("src/mcp_broker/absent.py", "0" * 64, "equivalent", frozenset({"func"})),
        Carveout("src/mcp_broker/sample.py", digest, "equivalent", frozenset({"func"})),
    ]
    results = [
        (
            "src/mcp_broker/sample.py",
            "src.mcp_broker.sample.x_func__mutmut_1",
            "survived",
        )
    ]

    excused, invalid = excusable_survivors(results, rows, repo_root=tmp_path)

    assert excused == {"src.mcp_broker.sample.x_func__mutmut_1"}
    assert len(invalid) == 1
    assert "absent.py" in invalid[0]


def test_a_killed_mutant_does_not_stop_a_later_survivor_being_excused(tmp_path: Path):
    """Killed mutants are not excusable, but they are not the end of the list."""
    digest = _write_source(tmp_path, "src/mcp_broker/sample.py", "x = 1\n")
    rows = [
        Carveout("src/mcp_broker/sample.py", digest, "equivalent", frozenset({"func"}))
    ]
    results = [
        ("src/mcp_broker/sample.py", "src.mcp_broker.sample.x_func__mutmut_1", "killed"),
        ("src/mcp_broker/sample.py", "src.mcp_broker.sample.x_func__mutmut_2", "survived"),
    ]

    excused, _ = excusable_survivors(results, rows, repo_root=tmp_path)

    assert excused == {"src.mcp_broker.sample.x_func__mutmut_2"}


def test_a_result_for_an_unverified_source_does_not_stop_a_later_one(tmp_path: Path):
    """A source with no verified rows excuses nothing and blocks nothing."""
    digest = _write_source(tmp_path, "src/mcp_broker/sample.py", "x = 1\n")
    rows = [
        Carveout("src/mcp_broker/sample.py", digest, "equivalent", frozenset({"func"}))
    ]
    results = [
        ("src/mcp_broker/other.py", "src.mcp_broker.other.x_func__mutmut_1", "survived"),
        (
            "src/mcp_broker/sample.py",
            "src.mcp_broker.sample.x_func__mutmut_2",
            "survived",
        ),
    ]

    excused, _ = excusable_survivors(results, rows, repo_root=tmp_path)

    assert excused == {"src.mcp_broker.sample.x_func__mutmut_2"}


def test_a_name_the_engine_did_not_generate_does_not_stop_a_later_survivor(
    tmp_path: Path,
):
    """An unrecognised mutant name is skipped; the next result still counts."""
    digest = _write_source(tmp_path, "src/mcp_broker/sample.py", "x = 1\n")
    rows = [
        Carveout("src/mcp_broker/sample.py", digest, "equivalent", frozenset({"func"}))
    ]
    results = [
        ("src/mcp_broker/sample.py", "not-a-mutant-name", "survived"),
        (
            "src/mcp_broker/sample.py",
            "src.mcp_broker.sample.x_func__mutmut_2",
            "survived",
        ),
    ]

    excused, _ = excusable_survivors(results, rows, repo_root=tmp_path)

    assert excused == {"src.mcp_broker.sample.x_func__mutmut_2"}


def test_a_stale_row_reports_the_short_current_hash(tmp_path: Path):
    """The problem names a short prefix of the current hash, not a nearby one."""
    digest = _write_source(tmp_path, "src/mcp_broker/sample.py", "x = 1\n")
    rows = [
        Carveout("src/mcp_broker/sample.py", "0" * 64, "equivalent", frozenset({"func"}))
    ]

    _, invalid = excusable_survivors([], rows, repo_root=tmp_path)

    assert len(invalid) == 1
    assert f"current {digest[:12]};" in invalid[0]
    assert digest[:13] not in invalid[0]
