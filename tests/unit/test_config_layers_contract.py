from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


def test_compose_layered_config_merges_in_fixed_order_and_reports_digest() -> None:
    from mcp_broker.config_layers import LayerDocument, compose_layered_config

    org = LayerDocument(
        name="org",
        source=Path("org.yaml"),
        data={
            "clients": {"codex": {"command": "mcp-broker-client"}},
            "profiles": {"codex": {"tools": ["broker_search_tools"]}},
            "upstreams": {"github": {"enabled": False, "call_timeout_seconds": 30}},
        },
    )
    team = LayerDocument(
        name="team",
        source=Path("team.yaml"),
        data={
            "clients": {"codex": {"command": "team-mcp-broker-client"}},
            "upstreams": {"github": {"enabled": True}},
        },
    )
    add_on = LayerDocument(
        name="observability",
        source=Path("observability.yaml"),
        data={
            "policy": {"audit": {"enabled": True}},
            "upstreams": {"github": {"call_timeout_seconds": 20}},
        },
    )
    user = LayerDocument(
        name="user",
        source=Path("user.yaml"),
        data={"upstreams": {"github": {"call_timeout_seconds": 10}}},
    )

    result = compose_layered_config(org=org, team=team, add_ons=[add_on], user=user)

    assert result.effective_config == {
        "clients": {"codex": {"command": "team-mcp-broker-client"}},
        "policy": {"audit": {"enabled": True}},
        "profiles": {"codex": {"tools": ["broker_search_tools"]}},
        "upstreams": {"github": {"enabled": True, "call_timeout_seconds": 10}},
    }
    assert result.digest.startswith("sha256:")
    assert result.layers == ["org", "team", "observability", "user"]
    assert result.provenance == {
        "clients.codex.command": {"layer": "team", "source": "team.yaml"},
        "policy.audit.enabled": {
            "layer": "observability",
            "source": "observability.yaml",
        },
        "profiles.codex.tools": {"layer": "org", "source": "org.yaml"},
        "upstreams.github.call_timeout_seconds": {
            "layer": "user",
            "source": "user.yaml",
        },
        "upstreams.github.enabled": {"layer": "team", "source": "team.yaml"},
    }
    assert result.conflicts == [
        {
            "path": "clients.codex.command",
            "previous_layer": "org",
            "new_layer": "team",
        },
        {
            "path": "upstreams.github.enabled",
            "previous_layer": "org",
            "new_layer": "team",
        },
        {
            "path": "upstreams.github.call_timeout_seconds",
            "previous_layer": "org",
            "new_layer": "observability",
        },
        {
            "path": "upstreams.github.call_timeout_seconds",
            "previous_layer": "observability",
            "new_layer": "user",
        },
    ]
    assert result.as_summary()["changed_runtime_state"] is False


def test_compose_layered_config_rejects_literal_secret_values() -> None:
    from mcp_broker.config_layers import (
        ConfigLayerError,
        LayerDocument,
        compose_layered_config,
    )

    org = LayerDocument(
        name="org",
        source=Path("org.yaml"),
        data={
            "upstreams": {
                "github": {
                    "env": {
                        "GITHUB_TOKEN": {"secret_ref": "GITHUB_TOKEN"},
                        "BAD_API_KEY": "plain-secret-value",
                    }
                }
            }
        },
    )

    with pytest.raises(ConfigLayerError, match="literal secret value"):
        compose_layered_config(org=org)


def test_compose_layered_config_rejects_invalid_secret_ref_names() -> None:
    from mcp_broker.config_layers import (
        ConfigLayerError,
        LayerDocument,
        compose_layered_config,
    )

    org = LayerDocument(
        name="org",
        source=Path("org.yaml"),
        data={"upstreams": {"github": {"env": {"TOKEN": {"secret_ref": "token-value"}}}}},
    )

    with pytest.raises(ConfigLayerError, match="secret_ref must name an environment variable"):
        compose_layered_config(org=org)


def test_compose_layered_config_requires_at_least_one_layer() -> None:
    from mcp_broker.config_layers import ConfigLayerError, compose_layered_config

    with pytest.raises(ConfigLayerError, match="at least one config layer is required"):
        compose_layered_config()


def test_compose_layered_config_handles_parent_replacements() -> None:
    from mcp_broker.config_layers import LayerDocument, compose_layered_config

    org = LayerDocument(
        name="org",
        source=Path("org.yaml"),
        data={"upstreams": {"github": {"enabled": True}}},
    )
    team = LayerDocument(
        name="team",
        source=Path("team.yaml"),
        data={"upstreams": {"github": "disabled-by-policy"}},
    )
    user = LayerDocument(
        name="user",
        source=Path("user.yaml"),
        data={"upstreams": {"github": {"enabled": False}}},
    )

    result = compose_layered_config(org=org, team=team, user=user)

    assert result.effective_config == {"upstreams": {"github": {"enabled": False}}}
    assert result.conflicts == [
        {
            "path": "upstreams.github",
            "previous_layer": "org",
            "new_layer": "team",
        },
        {
            "path": "upstreams.github",
            "previous_layer": "team",
            "new_layer": "user",
        },
    ]
    assert result.provenance == {
        "upstreams.github.enabled": {"layer": "user", "source": "user.yaml"}
    }
