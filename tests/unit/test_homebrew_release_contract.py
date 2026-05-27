from __future__ import annotations

from pathlib import Path

import pytest

from scripts.update_homebrew_formula import (
    FormulaUpdate,
    find_sdist_release,
    render_formula_update,
)


pytestmark = pytest.mark.unit


FORMULA_TEXT = """class McpBroker < Formula
  desc "Local MCP broker"
  homepage "https://github.com/NavinAgrawal/mcp-broker"
  url "https://files.pythonhosted.org/packages/old/mcp_broker-1.1.0.tar.gz"
  sha256 "oldsha"
  license "MIT"
end
"""


def test_homebrew_formula_update_replaces_pypi_sdist_url_and_sha() -> None:
    update = FormulaUpdate(
        url="https://files.pythonhosted.org/packages/new/mcp_broker-1.1.1.tar.gz",
        sha256="b559c8a09cdb17142cb30b30649ec6d5b1a41f8a8ad4d803aae71144ddcac877",
    )

    rendered = render_formula_update(FORMULA_TEXT, update)

    assert 'url "https://files.pythonhosted.org/packages/new/mcp_broker-1.1.1.tar.gz"' in rendered
    assert 'sha256 "b559c8a09cdb17142cb30b30649ec6d5b1a41f8a8ad4d803aae71144ddcac877"' in rendered
    assert "mcp_broker-1.1.0.tar.gz" not in rendered
    assert "oldsha" not in rendered


def test_homebrew_formula_update_is_idempotent_when_already_current() -> None:
    update = FormulaUpdate(
        url="https://files.pythonhosted.org/packages/old/mcp_broker-1.1.0.tar.gz",
        sha256="oldsha",
    )

    assert render_formula_update(FORMULA_TEXT, update) == FORMULA_TEXT


def test_homebrew_formula_update_rejects_formula_without_sdist_url() -> None:
    update = FormulaUpdate(url="https://example.invalid/mcp_broker-1.1.1.tar.gz", sha256="sha")

    with pytest.raises(ValueError, match="formula url line"):
        render_formula_update("class McpBroker < Formula\nend\n", update)


def test_find_sdist_release_uses_only_sdist_entries() -> None:
    payload = {
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "url": "https://example.invalid/mcp_broker-1.1.1-py3-none-any.whl",
                "digests": {"sha256": "wheelsha"},
            },
            {
                "packagetype": "sdist",
                "url": "https://example.invalid/mcp_broker-1.1.1.tar.gz",
                "digests": {"sha256": "sdistsha"},
            },
        ]
    }

    assert find_sdist_release(payload) == FormulaUpdate(
        url="https://example.invalid/mcp_broker-1.1.1.tar.gz",
        sha256="sdistsha",
    )


def test_homebrew_formula_script_uses_logging_not_print() -> None:
    script = Path("scripts/update_homebrew_formula.py").read_text(encoding="utf-8")

    assert "import logging" in script
    assert "print(" not in script
