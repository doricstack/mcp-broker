from __future__ import annotations

from pathlib import Path

import pytest

from scripts.update_homebrew_formula import (
    FormulaUpdate,
    fetch_pypi_release,
    find_sdist_release,
    render_formula_update,
)


pytestmark = pytest.mark.unit

OLD_VERSION = ".".join(("1", "1", "0"))
NEW_VERSION = ".".join(("1", "1", "1"))
OLD_SDIST_URL = f"https://files.pythonhosted.org/packages/old/mcp_broker-{OLD_VERSION}.tar.gz"
NEW_SDIST_URL = f"https://files.pythonhosted.org/packages/new/mcp_broker-{NEW_VERSION}.tar.gz"
EXAMPLE_SDIST_URL = f"https://example.invalid/mcp_broker-{NEW_VERSION}.tar.gz"
EXAMPLE_WHEEL_URL = f"https://example.invalid/mcp_broker-{NEW_VERSION}-py3-none-any.whl"

FORMULA_TEXT = """class McpBroker < Formula
  desc "Local MCP broker"
  homepage "https://example.invalid/example-broker"
  url "__OLD_SDIST_URL__"
  sha256 "oldsha"
  license "MIT"
end
""".replace("__OLD_SDIST_URL__", OLD_SDIST_URL)


def test_homebrew_formula_update_replaces_pypi_sdist_url_and_sha() -> None:
    update = FormulaUpdate(
        url=NEW_SDIST_URL,
        sha256="b559c8a09cdb17142cb30b30649ec6d5b1a41f8a8ad4d803aae71144ddcac877",
    )

    rendered = render_formula_update(FORMULA_TEXT, update)

    assert f'url "{NEW_SDIST_URL}"' in rendered
    assert 'sha256 "b559c8a09cdb17142cb30b30649ec6d5b1a41f8a8ad4d803aae71144ddcac877"' in rendered
    assert f"mcp_broker-{OLD_VERSION}.tar.gz" not in rendered
    assert "oldsha" not in rendered


def test_homebrew_formula_update_is_idempotent_when_already_current() -> None:
    update = FormulaUpdate(
        url=OLD_SDIST_URL,
        sha256="oldsha",
    )

    assert render_formula_update(FORMULA_TEXT, update) == FORMULA_TEXT


def test_homebrew_formula_update_rejects_formula_without_sdist_url() -> None:
    update = FormulaUpdate(url=EXAMPLE_SDIST_URL, sha256="sha")

    with pytest.raises(ValueError, match="formula url line"):
        render_formula_update("class McpBroker < Formula\nend\n", update)


def test_find_sdist_release_uses_only_sdist_entries() -> None:
    payload = {
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "url": EXAMPLE_WHEEL_URL,
                "digests": {"sha256": "wheelsha"},
            },
            {
                "packagetype": "sdist",
                "url": EXAMPLE_SDIST_URL,
                "digests": {"sha256": "sdistsha"},
            },
        ]
    }

    assert find_sdist_release(payload) == FormulaUpdate(
        url=EXAMPLE_SDIST_URL,
        sha256="sdistsha",
    )


def test_homebrew_formula_script_uses_logging_not_print() -> None:
    script = Path("scripts/update_homebrew_formula.py").read_text(encoding="utf-8")

    assert "import logging" in script
    assert "print(" not in script


def test_fetch_pypi_release_retries_until_json_is_available() -> None:
    class Response:
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"urls": []}'

    calls = 0
    sleeps: list[float] = []

    def opener(_url: str, timeout: int) -> Response:
        nonlocal calls
        calls += 1
        assert timeout == 30
        if calls < 3:
            raise OSError("not propagated")
        return Response()

    assert fetch_pypi_release(
        f"https://example.invalid/pypi/example-broker/{NEW_VERSION}/json",
        NEW_VERSION,
        attempts=4,
        retry_delay_seconds=0.25,
        opener=opener,
        sleeper=sleeps.append,
    ) == {"urls": []}
    assert calls == 3
    assert sleeps == [0.25, 0.25]


def test_fetch_pypi_release_fails_after_retry_budget() -> None:
    def opener(_url: str, timeout: int) -> object:
        raise OSError("still missing")

    with pytest.raises(ValueError, match="PyPI release payload unavailable"):
        fetch_pypi_release(
            f"https://example.invalid/pypi/example-broker/{NEW_VERSION}/json",
            NEW_VERSION,
            attempts=2,
            retry_delay_seconds=0,
            opener=opener,
            sleeper=lambda _seconds: None,
        )
