"""Validate mutmut metadata as a release gate."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp_broker.mutation_carveouts import excusable_survivors, parse_registry


STATUS_BY_EXIT_CODE = {
    0: "survived",
    1: "killed",
    2: "check_was_interrupted_by_user",
    3: "killed",
    5: "no_tests",
    24: "timeout",
    33: "no_tests",
    34: "skipped",
    35: "suspicious",
    36: "timeout",
    37: "caught_by_type_check",
    152: "timeout",
    255: "timeout",
    -24: "timeout",
    -11: "segfault",
    -9: "segfault",
}

ALL_STATUSES = [
    "killed",
    "caught_by_type_check",
    "survived",
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
    "not_checked",
]

PASS_STATUSES = {"killed", "caught_by_type_check"}
DEFAULT_FAIL_STATUSES = [status for status in ALL_STATUSES if status not in PASS_STATUSES]
DEFAULT_EXAMPLE_LIMIT = 10


@dataclass(frozen=True)
class MutationReport:
    counts: dict[str, int]
    total: int
    passed: int
    score: float
    blocked_by_file: list[dict[str, Any]]
    missing_selected_mutants: list[str] = field(default_factory=list)
    # Survivors the carve-out registry excused, and rows it could not apply.
    # Both are reported: a pass that hides what it excused is not a pass.
    excused_count: int = 0
    invalid_carveouts: list[str] = field(default_factory=list)
    # Excused mutants by status, so blocking_counts can net them out per status
    # rather than assuming they were all survivors.
    excused_by_status: dict[str, int] = field(default_factory=dict)

    @property
    def blocking_counts(self) -> dict[str, int]:
        """Raw counts minus what the registry excused, per status."""
        return {
            status: count - self.excused_by_status.get(status, 0)
            for status, count in self.counts.items()
        }

    @property
    def effective_score(self) -> float:
        """Score crediting excused survivors, for the min-score comparison.

        The raw `score` stays as measured. This one answers a different question:
        what fraction of mutants is either killed or adjudicated equivalent.
        """
        if self.total == 0:
            return 0.0
        return (self.passed + self.excused_count) / self.total * 100.0


def write_line(message: str) -> None:
    sys.stdout.write(f"{message}\n")


def status_for_exit_code(exit_code: Any) -> str:
    if exit_code is None:
        return "not_checked"
    if isinstance(exit_code, bool):
        return "suspicious"
    if isinstance(exit_code, int):
        return STATUS_BY_EXIT_CODE.get(exit_code, "suspicious")
    return "suspicious"


def mutant_source_path(meta_path: Path, mutants_dir: Path) -> str:
    relative = meta_path.relative_to(mutants_dir)
    path_text = relative.as_posix()
    if path_text.endswith(".meta"):
        path_text = path_text[: -len(".meta")]
    return path_text


def load_mutant_results(mutants_dir: Path) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    for meta_path in sorted(mutants_dir.rglob("*.meta")):
        data = json.loads(meta_path.read_bytes())
        if not isinstance(data, dict):
            raise ValueError(f"{meta_path} has no metadata object")
        raw_codes = data.get("exit_code_by_key")
        if not isinstance(raw_codes, dict):
            raise ValueError(f"{meta_path} has no object exit_code_by_key")
        source_path = mutant_source_path(meta_path, mutants_dir)
        for mutant_name, exit_code in sorted(raw_codes.items()):
            results.append((source_path, str(mutant_name), status_for_exit_code(exit_code)))
    return results


def filter_mutant_results(
    results: list[tuple[str, str, str]],
    include_mutants: list[str] | None,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    if include_mutants is None:
        return results, []
    filtered = [
        result
        for result in results
        if any(fnmatch.fnmatchcase(result[1], pattern) for pattern in include_mutants)
    ]
    matched_patterns = {
        pattern
        for pattern in include_mutants
        if any(fnmatch.fnmatchcase(result[1], pattern) for result in results)
    }
    missing = sorted(set(include_mutants) - matched_patterns)
    return filtered, missing


def blocked_file_summary(
    results: list[tuple[str, str, str]],
    *,
    fail_statuses: list[str],
    example_limit: int,
    excused: set[str] | None = None,
) -> list[dict[str, Any]]:
    if example_limit < 0:
        raise ValueError("example_limit must be greater than or equal to 0")
    validate_fail_statuses(fail_statuses)
    by_file: dict[str, dict[str, Any]] = {}
    fail_set = set(fail_statuses)
    excused = set() if excused is None else excused
    for source_path, mutant_name, status in results:
        if mutant_name in excused:
            # Adjudicated equivalent, bound to this file's current hash. It still
            # appears in the raw counts; it simply does not block the gate.
            continue
        entry = by_file.setdefault(
            source_path,
            {
                "path": source_path,
                "counts": Counter(),
                "examples": {},
                "blocked": 0,
                "total": 0,
            },
        )
        entry["total"] += 1
        if status in fail_set:
            entry["blocked"] += 1
            entry["counts"][status] += 1
            examples = entry["examples"].setdefault(status, [])
            if len(examples) < example_limit:
                examples.append(mutant_name)

    blocked = [entry for entry in by_file.values() if entry["blocked"] > 0]
    for entry in blocked:
        entry["counts"] = dict(sorted(entry["counts"].items()))
        entry["examples"] = dict(sorted(entry["examples"].items()))
    return sorted(blocked, key=lambda entry: (-entry["blocked"], entry["path"]))


def validate_fail_statuses(fail_statuses: list[str]) -> None:
    unknown = sorted(set(fail_statuses) - set(ALL_STATUSES))
    if unknown:
        raise ValueError(f"unknown fail status: {', '.join(unknown)}")


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be greater than or equal to 0")
    return parsed


def build_report(
    mutants_dir: Path,
    *,
    fail_statuses: list[str] | None = None,
    example_limit: int | None = None,
    include_mutants: list[str] | None = None,
    carveouts_path: Path | None = None,
    repo_root: Path | None = None,
) -> MutationReport:
    if not mutants_dir.is_dir():
        raise FileNotFoundError(f"Mutants directory does not exist: {mutants_dir}")

    fail_statuses = [] if fail_statuses is None else fail_statuses
    example_limit = DEFAULT_EXAMPLE_LIMIT if example_limit is None else example_limit
    validate_fail_statuses(fail_statuses)
    counts = {status: 0 for status in ALL_STATUSES}
    results, missing_selected_mutants = filter_mutant_results(
        load_mutant_results(mutants_dir),
        include_mutants,
    )
    for _source_path, _mutant_name, status in results:
        counts[status] += 1

    total = sum(counts.values())
    passed = counts["killed"] + counts["caught_by_type_check"]
    score = 0.0 if total == 0 else passed / total * 100.0
    # A registry is honored only when the caller supplies both the registry and
    # the root to hash sources against. Without a root there is nothing to verify
    # the recorded hash against, so the safe answer is to excuse nothing.
    excused: set[str] = set()
    invalid_carveouts: list[str] = []
    if carveouts_path is not None and repo_root is not None:
        rows = parse_registry(carveouts_path)
        excused, invalid_carveouts = excusable_survivors(
            results, rows, repo_root=repo_root
        )

    excused_by_status: dict[str, int] = {}
    for _source_path, mutant_name, status in results:
        if mutant_name in excused:
            excused_by_status[status] = excused_by_status.get(status, 0) + 1

    blocked = blocked_file_summary(
        results,
        fail_statuses=fail_statuses,
        example_limit=example_limit,
        excused=excused,
    )
    return MutationReport(
        counts=counts,
        total=total,
        passed=passed,
        score=score,
        blocked_by_file=blocked,
        missing_selected_mutants=missing_selected_mutants,
        excused_count=len(excused),
        invalid_carveouts=invalid_carveouts,
        excused_by_status=excused_by_status,
    )


def write_report(report: MutationReport, output_json: Path) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_bytes(
        (
            json.dumps(
                {
                    "counts": report.counts,
                    "total": report.total,
                    "passed": report.passed,
                    "score": report.score,
                    "blocked_by_file": report.blocked_by_file,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mutants-dir", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--min-score", type=float, default=100.0)
    parser.add_argument("--example-limit", type=non_negative_int, default=10)
    parser.add_argument(
        "--include-mutants",
        nargs="+",
        help="Optional mutant names to grade; unselected mutants are ignored.",
    )
    parser.add_argument(
        "--fail-statuses",
        nargs="+",
        choices=ALL_STATUSES,
        default=DEFAULT_FAIL_STATUSES,
    )
    parser.add_argument(
        "--carveouts",
        type=Path,
        help=(
            "Carve-out registry. Survivors it records as equivalent stop blocking, "
            "but only where the row's recorded SHA-256 matches the file's current "
            "hash. Requires --repo-root."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="Root the carve-out source paths are relative to, for hashing.",
    )
    return parser


def failure_exit_code(report: MutationReport, args: argparse.Namespace) -> int | None:
    # A carve-out bound to a hash the file no longer has cannot be applied. That
    # is a stale registry, not a pass: the recorded review was of different code.
    if report.invalid_carveouts:
        for problem in report.invalid_carveouts:
            write_line(f"Mutation gate failed: unusable carve-out: {problem}")
        write_line(
            "Refresh the recorded SHA-256 after re-reviewing, or remove the row. "
            f"Report: {args.output_json}"
        )
        return 1

    # Blocking counts are net of registered equivalents. The raw counts are
    # untouched in the report and its JSON, so an excused run stays legible as
    # one rather than reading as a clean sweep.
    blocked_by_status = {
        status: count
        for status, count in report.blocking_counts.items()
        if status in set(args.fail_statuses) and count > 0
    }
    blocked_counts = blocked_by_status
    if report.excused_count:
        write_line(
            f"Mutation gate: {report.excused_count} survivor(s) excused by "
            "docs/mutation-carveouts.md, each bound to its file's current hash."
        )
    if report.total == 0:
        if report.missing_selected_mutants:
            write_line(
                "Mutation gate failed: selected mutants not found: "
                + ", ".join(report.missing_selected_mutants)
                + f". Report: {args.output_json}"
            )
            return 1
        write_line(f"Mutation gate failed: no mutants found. Report: {args.output_json}")
        return 1
    if report.missing_selected_mutants:
        write_line(
            "Mutation gate failed: selected mutants not found: "
            + ", ".join(report.missing_selected_mutants)
            + f". Report: {args.output_json}"
        )
        return 1
    if blocked_counts:
        write_line(
            "Mutation gate failed: "
            + ", ".join(f"{status}={count}" for status, count in sorted(blocked_counts.items()))
            + f". Report: {args.output_json}"
        )
        return 1
    if report.effective_score < args.min_score:
        write_line(
            f"Mutation gate failed: score={report.effective_score:.2f}, "
            f"min_score={args.min_score:.2f}. Report: {args.output_json}"
        )
        return 1
    return None


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = build_report(
        args.mutants_dir,
        fail_statuses=args.fail_statuses,
        example_limit=args.example_limit,
        include_mutants=args.include_mutants,
        carveouts_path=args.carveouts,
        repo_root=args.repo_root,
    )
    write_report(report, args.output_json)

    if exit_code := failure_exit_code(report, args):
        return exit_code

    write_line(
        f"Mutation gate passed: score={report.score:.2f}, "
        f"passed={report.passed}, total={report.total}. Report: {args.output_json}"
    )
    return 0
