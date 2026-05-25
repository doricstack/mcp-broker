#!/usr/bin/env python3
"""Fail the Makefile gate when grade-quality reports anything below A+."""

from __future__ import annotations

import json
import sys
from pathlib import Path


MIN_SCORE = 97.0
BLOCKING_SEVERITIES = ("CRITICAL", "HIGH")


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: enforce_grade_quality.py <grade_quality_report.json>\n")
        return 2

    report_path = Path(sys.argv[1])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    score = float(report.get("score", 0.0))
    grade = str(report.get("quality_grade", "unknown"))
    severity_counts = report.get("severity_counts", {})
    blockers = {
        severity: int(severity_counts.get(severity, 0))
        for severity in BLOCKING_SEVERITIES
    }

    if score < MIN_SCORE or any(count > 0 for count in blockers.values()):
        sys.stderr.write(
            "grade-quality failed: "
            f"grade={grade} score={score:.1f} blockers={blockers}\n"
        )
        return 1

    sys.stdout.write(f"grade-quality passed: grade={grade} score={score:.1f}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
