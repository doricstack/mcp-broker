import json
from importlib import metadata
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def test_source_tree_version_reads_npm_package_version():
    import mcp_broker

    package_version = json.loads((Path(__file__).resolve().parents[2] / "npm" / "package.json").read_text())[
        "version"
    ]

    assert mcp_broker._source_tree_version() == package_version


def test_source_tree_version_requires_source_package_metadata(monkeypatch, tmp_path):
    import mcp_broker

    source_init = tmp_path / "src" / "mcp_broker" / "__init__.py"
    source_init.parent.mkdir(parents=True)
    source_init.write_text("", encoding="utf-8")
    monkeypatch.setattr(mcp_broker, "__file__", str(source_init))

    with pytest.raises(RuntimeError, match="MCP_BROKER_VERSION is required"):
        mcp_broker._source_tree_version()


def test_resolve_version_prefers_mcp_broker_version_environment(monkeypatch):
    import mcp_broker

    monkeypatch.setenv("MCP_BROKER_VERSION", " 9.8.7 ")
    monkeypatch.setattr(mcp_broker.metadata, "version", lambda _name: pytest.fail("metadata fallback was used"))

    assert mcp_broker._resolve_version() == "9.8.7"


def test_resolve_version_uses_installed_distribution_without_environment(monkeypatch):
    import mcp_broker

    monkeypatch.delenv("MCP_BROKER_VERSION", raising=False)
    monkeypatch.setattr(mcp_broker.metadata, "version", lambda name: "1.2.3" if name == "mcp-broker" else "wrong")
    monkeypatch.setattr(mcp_broker, "_source_tree_version", lambda: pytest.fail("source fallback was used"))

    assert mcp_broker._resolve_version() == "1.2.3"


def test_resolve_version_uses_source_tree_when_distribution_is_missing(monkeypatch):
    import mcp_broker

    def missing_distribution(_name):
        raise metadata.PackageNotFoundError

    monkeypatch.delenv("MCP_BROKER_VERSION", raising=False)
    monkeypatch.setattr(mcp_broker.metadata, "version", missing_distribution)
    monkeypatch.setattr(mcp_broker, "_source_tree_version", lambda: "4.5.6")

    assert mcp_broker._resolve_version() == "4.5.6"
