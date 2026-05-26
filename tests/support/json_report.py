import json
from typing import Any


def report_from_stdout(stdout: str, *, label: str) -> dict[str, Any]:
    for line in reversed(stdout.splitlines()):
        if not line.startswith("{"):
            continue
        try:
            report = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(report, dict):
            return report
    raise AssertionError(f"{label} did not emit a JSON report: {stdout!r}")
