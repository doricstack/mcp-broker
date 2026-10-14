"""Narrow mutmut's module unload so the mutation run cannot segfault.

mutmut 3.7.0 gathers "which lines do the tests cover" by running the whole suite
inside its own process, and then calls `_unload_modules_not_in`, which pops from
`sys.modules` every module that the run imported. The point is to make the
mutated copies importable afterwards. It also unloads third-party modules, and
re-importing a compiled extension in the same process loads a second copy of it.
Upstream documents the resulting crashes (issue 528); here the release gate died
with SIGSEGV in `record_trampoline_hit`, with `yaml._yaml` and
`setproctitle._setproctitle` loaded.

Only the mutated copies need to come out, and every one of them is imported from
`<workspace>/mutants`. Keeping everything else loaded removes the second import
without changing which code the mutants exercise.

Loaded through `PYTHONPATH` on the mutmut invocation, not into the repository's
normal test runs: the guard returns immediately unless `MUTMUT_UNLOAD_GUARD=1`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

GUARD_ENV_VAR = "MUTMUT_UNLOAD_GUARD"
MUTATED_SOURCE_DIRECTORY = "mutants"


def _mutants_root() -> str:
    return str((Path.cwd() / MUTATED_SOURCE_DIRECTORY).resolve()) + os.sep


def _came_from_the_mutant_tree(module: object, root: str) -> bool:
    filename = getattr(module, "__file__", None)
    if not filename:
        return False
    try:
        return str(Path(filename).resolve()).startswith(root)
    except OSError:
        return False


def install() -> bool:
    """Narrow the unload in place. True when the patch was applied."""
    try:
        from mutmut import code_coverage
    except Exception:
        return False

    if getattr(code_coverage, "_mcp_broker_unload_narrowed", False):
        return True

    root = _mutants_root()

    def _unload_modules_not_in(modules: dict) -> None:
        for name in list(sys.modules):
            if name == "mutmut.code_coverage":
                continue
            if name in modules:
                continue
            if not _came_from_the_mutant_tree(sys.modules.get(name), root):
                continue
            sys.modules.pop(name, None)
        import importlib

        importlib.invalidate_caches()

    code_coverage._unload_modules_not_in = _unload_modules_not_in
    code_coverage._mcp_broker_unload_narrowed = True
    return True


if os.environ.get(GUARD_ENV_VAR) == "1":
    install()
