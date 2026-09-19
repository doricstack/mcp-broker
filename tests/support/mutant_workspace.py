"""Whether this test process is running inside the mutation workspace.

The mutation container unpacks a copy of the tree, rewrites its mutation scope
in setup.cfg, and runs the selected tests there to score mutants. A test that
asserts the repository's own wiring - the shipped configuration, the git base
it diffs against - cannot speak to that copy, and failing there reports a
missing prerequisite as though it were a defect in the code under mutation.

The harness exports the marker, so a test that cannot run in the workspace
states that and steps aside instead of inferring it from a path shape.
"""

from __future__ import annotations

import os


MUTATION_WORKSPACE_ENV = "MCP_BROKER_MUTATION_WORKSPACE"


def in_mutant_workspace() -> bool:
    """True when the mutation container is scoring mutants in this tree."""
    return os.environ.get(MUTATION_WORKSPACE_ENV) == "1"
