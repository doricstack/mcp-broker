"""build_report excuses registered equivalents and reports what it excused.

The unit tests cover the registry semantics. These cover the wiring, which is
where the dangerous failure lives: a gate that quietly subtracts survivors and
prints a clean score is worse than the gate that failed honestly, because the
number looks the same as a real 100 percent.

So the contract is not only "the gate passes". It is that the excused count is
always visible, an unexcused survivor still fails, and a stale registry row
cannot launder anything.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mcp_broker.mutation_stats import build_parser, build_report, failure_exit_code


REGISTRY_HEADER = """# Mutation carve-outs

| ID | File and lines | Reason class | Exact candidate and explanation | Advisor sign-off |
|---|---|---|---|---|
"""


def _mutants_dir(tmp_path: Path, entries: list[tuple[str, str, int]]) -> Path:
    """Write a mutmut-shaped meta file. entries are (path, mutant_name, exit_code)."""
    mutants = tmp_path / "mutants"
    by_path: dict[str, list[tuple[str, int]]] = {}
    for source_path, mutant_name, exit_code in entries:
        by_path.setdefault(source_path, []).append((mutant_name, exit_code))
    for source_path, rows in by_path.items():
        meta = mutants / f"{source_path}.meta"
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(
            json.dumps(
                {
                    "exit_code_by_key": {name: code for name, code in rows},
                }
            ),
            encoding="utf-8",
        )
    return mutants


def _source(root: Path, rel: str, body: str) -> str:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return hashlib.sha256(target.read_bytes()).hexdigest()


def _registry(root: Path, rows: list[str]) -> Path:
    path = root / "docs" / "mutation-carveouts.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(REGISTRY_HEADER + "".join(rows), encoding="utf-8")
    return path


def _row(path: str, callables: str, reason: str, digest: str) -> str:
    return (
        f"| `{path}` | {callables}: the `\"utf-8\"` literals | {reason} | "
        f"mutmut 3.7.0; SHA-256 `{digest}` | signed off |\n"
    )


def test_a_registered_equivalent_survivor_no_longer_blocks(tmp_path: Path):
    digest = _source(tmp_path, "src/mcp_broker/break_glass.py", "x = 1\n")
    registry = _registry(
        tmp_path, [_row("src/mcp_broker/break_glass.py", "`_read_json`", "equivalent", digest)]
    )
    mutants = _mutants_dir(
        tmp_path,
        [("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x__read_json__mutmut_7", 0)],
    )

    report = build_report(
        mutants,
        fail_statuses=["survived"],
        carveouts_path=registry,
        repo_root=tmp_path,
    )

    assert report.excused_count == 1
    assert report.blocked_by_file == []
    # The raw count is preserved: the survivor happened, it is just not blocking.
    assert report.counts["survived"] == 1


def test_an_unregistered_survivor_still_blocks(tmp_path: Path):
    digest = _source(tmp_path, "src/mcp_broker/break_glass.py", "x = 1\n")
    registry = _registry(
        tmp_path, [_row("src/mcp_broker/break_glass.py", "`_read_json`", "equivalent", digest)]
    )
    mutants = _mutants_dir(
        tmp_path,
        [
            ("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x__read_json__mutmut_7", 0),
            ("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x_other__mutmut_1", 0),
        ],
    )

    report = build_report(
        mutants,
        fail_statuses=["survived"],
        carveouts_path=registry,
        repo_root=tmp_path,
    )

    assert report.excused_count == 1
    assert len(report.blocked_by_file) == 1
    assert report.blocked_by_file[0]["blocked"] == 1
    assert report.blocked_by_file[0]["examples"]["survived"] == [
        "src.mcp_broker.break_glass.x_other__mutmut_1"
    ]


def test_a_stale_registry_row_launders_nothing_and_surfaces(tmp_path: Path):
    _source(tmp_path, "src/mcp_broker/break_glass.py", "x = 1\n")
    registry = _registry(
        tmp_path, [_row("src/mcp_broker/break_glass.py", "`_read_json`", "equivalent", "0" * 64)]
    )
    mutants = _mutants_dir(
        tmp_path,
        [("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x__read_json__mutmut_7", 0)],
    )

    report = build_report(
        mutants,
        fail_statuses=["survived"],
        carveouts_path=registry,
        repo_root=tmp_path,
    )

    assert report.excused_count == 0
    assert len(report.blocked_by_file) == 1
    assert report.invalid_carveouts, "a stale row must be reported, not silently ignored"


def test_no_registry_path_behaves_exactly_as_before(tmp_path: Path):
    """Absent a registry the gate must be unchanged, so this cannot loosen anything."""
    mutants = _mutants_dir(
        tmp_path,
        [("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x__read_json__mutmut_7", 0)],
    )

    report = build_report(mutants, fail_statuses=["survived"])

    assert report.excused_count == 0
    assert report.invalid_carveouts == []
    assert len(report.blocked_by_file) == 1


def test_a_timeout_is_never_excused_even_when_registered(tmp_path: Path):
    digest = _source(tmp_path, "src/mcp_broker/break_glass.py", "x = 1\n")
    registry = _registry(
        tmp_path, [_row("src/mcp_broker/break_glass.py", "`_read_json`", "equivalent", digest)]
    )
    # exit 24 is a timeout in the engine's status map.
    mutants = _mutants_dir(
        tmp_path,
        [("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x__read_json__mutmut_7", 24)],
    )

    report = build_report(
        mutants,
        fail_statuses=["timeout"],
        carveouts_path=registry,
        repo_root=tmp_path,
    )

    assert report.excused_count == 0
    assert len(report.blocked_by_file) == 1


def _args(output_json: Path, **overrides):
    parser = build_parser()
    argv = [
        "--mutants-dir",
        str(output_json.parent),
        "--output-json",
        str(output_json),
    ]
    for key, value in overrides.items():
        argv += [f"--{key.replace('_', '-')}", str(value)]
    return parser.parse_args(argv)


def test_the_gate_passes_when_every_survivor_is_registered(tmp_path: Path):
    digest = _source(tmp_path, "src/mcp_broker/break_glass.py", "x = 1\n")
    registry = _registry(
        tmp_path, [_row("src/mcp_broker/break_glass.py", "`_read_json`", "equivalent", digest)]
    )
    mutants = _mutants_dir(
        tmp_path,
        [
            ("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x__read_json__mutmut_7", 0),
            ("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x_killed__mutmut_1", 1),
        ],
    )
    report = build_report(
        mutants, fail_statuses=["survived"], carveouts_path=registry, repo_root=tmp_path
    )

    args = _args(tmp_path / "report.json", fail_statuses="survived", min_score=100.0)
    assert failure_exit_code(report, args) is None


def test_the_gate_still_fails_on_one_unregistered_survivor(tmp_path: Path):
    digest = _source(tmp_path, "src/mcp_broker/break_glass.py", "x = 1\n")
    registry = _registry(
        tmp_path, [_row("src/mcp_broker/break_glass.py", "`_read_json`", "equivalent", digest)]
    )
    mutants = _mutants_dir(
        tmp_path,
        [
            ("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x__read_json__mutmut_7", 0),
            ("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x_other__mutmut_1", 0),
        ],
    )
    report = build_report(
        mutants, fail_statuses=["survived"], carveouts_path=registry, repo_root=tmp_path
    )

    args = _args(tmp_path / "report.json", fail_statuses="survived", min_score=100.0)
    assert failure_exit_code(report, args) == 1


def test_a_stale_carveout_row_fails_the_gate(tmp_path: Path):
    """The review was of different code, so the row cannot be trusted or ignored."""
    _source(tmp_path, "src/mcp_broker/break_glass.py", "x = 1\n")
    registry = _registry(
        tmp_path, [_row("src/mcp_broker/break_glass.py", "`_read_json`", "equivalent", "0" * 64)]
    )
    mutants = _mutants_dir(
        tmp_path,
        [("src/mcp_broker/break_glass.py", "src.mcp_broker.break_glass.x_killed__mutmut_1", 1)],
    )
    report = build_report(
        mutants, fail_statuses=["survived"], carveouts_path=registry, repo_root=tmp_path
    )

    # Nothing survived, so only the stale row can fail this run.
    assert report.counts["survived"] == 0
    args = _args(tmp_path / "report.json", fail_statuses="survived", min_score=100.0)
    assert failure_exit_code(report, args) == 1
