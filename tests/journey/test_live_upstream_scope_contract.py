"""The live upstream sweep must not race itself.

`tests/live/test_real_upstream_centralization.py` parametrizes one case per enabled
upstream, and each case starts a real MCP server. With 23 enabled upstreams, 21 of
them stdio, an xdist run spawns up to 21 cold processes at once, every one of them
racing the same 10s ready budget.

Measured 2026-09-07 during a release gate: that sweep failed with
`upstream timed out: mermaid` at 1447 passed, 1 failed, on a machine at load 18.
The server itself was never slow. It answers initialize in 0.48s to 1.46s across
five runs at load 14, the single case passes in 1.44s, and the production daemon
logs 2491 of those calls with zero timeouts.

So the budget was not the defect; the self-inflicted storm was. Raising the timeout
would have bought a number tuned to one evening's load. Pinning the cases to a
single xdist worker removes the contention instead, and leaves the 10s budget with
roughly seven times headroom against the slowest measured cold start.

A gate that fails on machine load teaches sessions to rerun until green, and a
rerun-until-green gate is one whose output nobody reads while it still costs a
governor lane every time.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.journey

ROOT = Path(__file__).resolve().parents[2]
LIVE_SWEEP = ROOT / "tests" / "live" / "test_real_upstream_centralization.py"


def sweep_source() -> str:
    assert LIVE_SWEEP.is_file(), f"{LIVE_SWEEP} is missing; the contract cannot hold"
    return LIVE_SWEEP.read_text(encoding="utf-8")


def test_the_upstream_sweep_is_pinned_to_one_xdist_worker():
    """xdist_group keeps every parametrized case on the same worker, so the real
    servers start one at a time instead of 21 at once."""
    source = sweep_source()
    assert "xdist_group" in source, (
        "the live upstream sweep must carry an xdist_group marker; without it each "
        "parametrized case spawns a real MCP server concurrently with every other, "
        "and they race the same ready budget")


def test_the_sweep_marker_names_a_single_shared_group():
    """One group name for the whole file, so cases cannot be split across workers."""
    source = sweep_source()
    groups = set(re.findall(r'xdist_group\(name="([^"]+)"\)', source))
    assert len(groups) == 1, (
        f"expected exactly one xdist_group name in the sweep, found {sorted(groups)}; "
        "two groups can run on two workers and the storm returns")


def test_the_sweep_still_covers_every_enabled_upstream():
    """Serialising must not narrow what the gate examines.

    An empty or reduced sweep would report the same green while proving less, which
    is the failure empty-scope-is-not-success exists to prevent.
    """
    source = sweep_source()
    assert "_configured_upstream_names()" in source, (
        "the sweep must still derive its cases from the configured upstreams")
    assert "metafunc.parametrize" in source, (
        "the sweep must still parametrize over those upstreams rather than "
        "collapsing to a single case")
