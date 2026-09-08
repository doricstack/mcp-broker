"""A release cut must be able to scope its own mutation run.

`MUTATION_DIFF_BASE` is `origin/main`, which answers "what is unmerged". That is the
right question for a feature branch and the wrong one for a release, where the
branch IS main and nothing is unmerged. A release gate hit exactly that: the
selector returned zero files and the run refused with

    release-gate selected zero changed source files; refusing unscoped mutation

Refusing was correct, because a mutation run that mutates nothing must never report
the same green as one that mutated everything. What was missing is the distinction
empty-scope-is-not-success EGS-2.1 asks for: "the selector found nothing because
there is genuinely nothing" and "the selector is asking the wrong question" are
different states, and only one of them is the operator's fault to fix.

So the release path gets its own base, defaulting to the ordinary one, and the
refusal names the release case when HEAD already matches that base.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.journey

ROOT = Path(__file__).resolve().parents[2]
RELEASE_MK = ROOT / "mk" / "release.mk"
CONFIG_MK = ROOT / "mk" / "config.mk"


def release_block() -> str:
    text = RELEASE_MK.read_text(encoding="utf-8")
    assert "_release-gate-mutation-run:" in text, "release mutation target is missing"
    return text.split("_release-gate-mutation-run:", maxsplit=1)[1]


def test_config_declares_a_release_specific_mutation_diff_base():
    """Feature branches ask what is unmerged; a release asks what is new since the
    last release. Those are different bases and need different variables."""
    text = CONFIG_MK.read_text(encoding="utf-8")
    assert "RELEASE_MUTATION_DIFF_BASE" in text, (
        "mk/config.mk must declare RELEASE_MUTATION_DIFF_BASE so a release cut can "
        "scope its mutation run against the last released version rather than "
        "against origin/main, which a release cut already matches")


def test_the_release_base_defaults_to_the_ordinary_base():
    """Nothing changes for an ordinary run: the default keeps today's behaviour."""
    text = CONFIG_MK.read_text(encoding="utf-8")
    assert "RELEASE_MUTATION_DIFF_BASE ?= $(MUTATION_DIFF_BASE)" in text, (
        "the release base must default to MUTATION_DIFF_BASE so this is an "
        "additional lever rather than a behaviour change for every caller")


def test_the_release_gate_uses_the_release_base():
    assert "$(RELEASE_MUTATION_DIFF_BASE)" in release_block(), (
        "the release-gate mutation step must select against the release base")


def test_the_refusal_distinguishes_a_release_cut_from_a_broken_selector():
    """Both states print zero files today. Only one is fixed by passing a base."""
    block = release_block()
    assert "RELEASE_MUTATION_DIFF_BASE=" in block, (
        "the refusal must name the variable an operator sets to scope a release "
        "cut; a bare 'zero changed source files' sends them looking for a defect "
        "that is not there")


def test_the_release_gate_still_refuses_an_unscoped_run():
    """The fix must not turn an empty scope into a pass."""
    block = release_block()
    assert "refusing unscoped mutation" in block, (
        "an empty selection must still refuse; a mutation run over zero files "
        "reporting green is the defect this gate exists to prevent")
    assert "exit 2" in block, "the refusal must fail the gate, not warn"
