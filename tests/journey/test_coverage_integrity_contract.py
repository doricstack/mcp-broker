from pathlib import Path


import pytest


pytestmark = pytest.mark.journey


def test_source_does_not_hide_lines_from_coverage() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for path in sorted((repo_root / "src").rglob("*.py")):
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if "pragma: no cover" in line:
                offenders.append(f"{path.relative_to(repo_root)}:{line_number}")

    assert offenders == []
