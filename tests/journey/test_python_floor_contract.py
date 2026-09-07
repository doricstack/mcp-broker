"""Every shipped module must import on the oldest Python the package declares.

pyproject declares requires-python ">=3.10" and PyPI publishes that floor, so a
module using a 3.11-only name breaks every install on 3.10. Published 2.1.1 did
exactly that: `from datetime import UTC` in eight modules raised ImportError on
the CLI entrypoint for anyone on 3.10, and nothing in the suite noticed because
the whole suite runs on a newer interpreter.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "mcp_broker"

# Names these modules may not import from datetime while the floor allows 3.10.
DATETIME_NAMES_ADDED_AFTER_310 = {"UTC"}


def declared_floor() -> tuple[int, int]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'requires-python\s*=\s*">=(\d+)\.(\d+)"', text)
    assert match, "pyproject must declare a requires-python floor"
    return int(match.group(1)), int(match.group(2))


def source_files() -> list[Path]:
    files = sorted(SRC.rglob("*.py"))
    assert files, "no shipped modules found to check"
    return files


def test_no_shipped_module_imports_a_name_newer_than_the_declared_floor():
    """A 3.11-only datetime name is an ImportError on the declared floor."""
    assert declared_floor() == (3, 10)
    offenders = []
    for path in source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "datetime":
                for alias in node.names:
                    if alias.name in DATETIME_NAMES_ADDED_AFTER_310:
                        offenders.append(
                            f"{path.relative_to(ROOT)}:{node.lineno} imports {alias.name}")
    assert offenders == [], (
        "these modules cannot import on Python 3.10; use timezone.utc instead of UTC: "
        + "; ".join(offenders))


def floor_interpreter() -> str | None:
    """Locate an interpreter at the declared floor without naming any user path."""
    major, minor = declared_floor()
    override = os.environ.get("PYTHON_FLOOR_INTERPRETER")
    if override and Path(override).is_file():
        return override
    found = shutil.which(f"python{major}.{minor}")
    if found:
        return found
    # uv keeps downloaded interpreters under its own data directory.
    uv_root = Path(os.environ.get("UV_PYTHON_INSTALL_DIR")
                   or Path.home() / ".local" / "share" / "uv" / "python")
    for candidate in sorted(uv_root.glob(f"cpython-{major}.{minor}.*/bin/python3")):
        return str(candidate)
    return None


@pytest.mark.skipif(floor_interpreter() is None,
                    reason="no interpreter at the declared floor is installed")
def test_every_shipped_module_imports_on_the_floor_interpreter():
    """Static scanning catches known names; only the real floor catches the rest."""
    interpreter = floor_interpreter()
    assert interpreter is not None, "skipif should have prevented this"
    modules = sorted(
        ".".join(path.relative_to(SRC.parent).with_suffix("").parts)
        for path in source_files()
        if path.name != "__init__.py" and not path.name.startswith("_"))
    assert modules, "no importable modules resolved"
    program = (
        "import importlib, sys\n"
        "bad = []\n"
        "for name in sys.argv[1:]:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except ImportError as error:\n"
        "        bad.append(f'{name}: {error}')\n"
        "    except Exception:\n"
        "        pass\n"  # missing third-party deps and runtime wiring are not floor failures
        "print('\\n'.join(bad))\n")
    result = subprocess.run(
        [interpreter, "-c", program, *modules],
        capture_output=True, text=True, timeout=300, cwd=str(ROOT),
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"})
    assert result.returncode == 0, result.stderr
    offenders = [line for line in result.stdout.splitlines()
                 if "cannot import name" in line or "No module named 'datetime'" in line]
    assert offenders == [], (
        "these shipped modules raise ImportError on the declared floor:\n"
        + "\n".join(offenders))
