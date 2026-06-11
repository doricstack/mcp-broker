import json
from pathlib import Path

import pytest

from mcp_broker.broker import BrokerToolError
from mcp_broker.catalog import (
    BrokerCatalogFacade,
    _specific_query_can_select_upstream,
    catalog_entries_for_upstream,
    catalog_entry_matches,
    catalog_unavailable_entry_for_upstream,
    profile_allows_upstream,
    structured_tool_result,
    upstream_metadata_matches,
    upstream_owns_tool_name,
)
from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig, SmokeProbe, UpstreamConfig
from mcp_broker.profiles import ToolExposureProfile


pytestmark = pytest.mark.unit


def test_catalog_entry_matching_uses_any_token_relevance() -> None:
    entry = {
        "name": "work-store.search_items",
        "upstream": "work-store",
        "description": "Search project records",
        "purpose": "Project collaboration",
        "tags": ["records", "read-only"],
    }

    assert catalog_entry_matches(entry, "")
    assert catalog_entry_matches(entry, "work-store records")
    assert catalog_entry_matches(entry, "SEARCH project")
    # A partial natural-language query still matches on its present tokens, instead
    # of returning nothing the moment one word ("missing") is absent.
    assert catalog_entry_matches(entry, "work-store missing")
    assert not catalog_entry_matches(entry, "unknown")


def test_catalog_entry_score_weights_name_over_purpose_over_description() -> None:
    from mcp_broker.catalog import (
        _SCORE_DESCRIPTION,
        _SCORE_NAME,
        _SCORE_PURPOSE,
        catalog_entry_score,
    )

    assert _SCORE_NAME > _SCORE_PURPOSE > _SCORE_DESCRIPTION
    assert catalog_entry_score({"name": "deploy"}, "deploy") == _SCORE_NAME
    assert catalog_entry_score({"tags": ["deploy"]}, "deploy") == _SCORE_NAME
    assert catalog_entry_score({"purpose": "deploy"}, "deploy") == _SCORE_PURPOSE
    assert catalog_entry_score({"description": "deploy"}, "deploy") == _SCORE_DESCRIPTION
    # Each token counts its single strongest field, not every field it appears in.
    assert catalog_entry_score({"name": "deploy", "description": "deploy"}, "deploy") == _SCORE_NAME
    # Scores accumulate across matching tokens; absent tokens add nothing.
    assert catalog_entry_score({"name": "fly deploy"}, "fly deploy nonsense") == 2 * _SCORE_NAME
    # Different tiers accumulate (a prior token's score is added to, not overwritten).
    tiered = {"name": "alpha", "purpose": "bravo", "description": "charlie"}
    assert catalog_entry_score(tiered, "alpha bravo") == _SCORE_NAME + _SCORE_PURPOSE
    assert catalog_entry_score(tiered, "alpha charlie") == _SCORE_NAME + _SCORE_DESCRIPTION
    # Empty query is a uniform non-zero score (full catalog passes the filter).
    assert catalog_entry_score({"name": "x"}, "") == _SCORE_NAME
    assert catalog_entry_score({}, "missing") == 0


@pytest.mark.parametrize(
    "query",
    ["alpha-tool", "beta-upstream", "gamma-description", "delta-purpose", "epsilon-tag"],
)
def test_catalog_entry_matching_indexes_each_catalog_field(query: str) -> None:
    entry = {
        "name": "alpha-tool",
        "upstream": "beta-upstream",
        "description": "gamma-description",
        "purpose": "delta-purpose",
        "tags": ["epsilon-tag", "zeta-tag"],
    }

    assert catalog_entry_matches(entry, query)


def test_catalog_entry_matching_does_not_index_missing_field_defaults() -> None:
    assert not catalog_entry_matches({}, "none")
    assert not catalog_entry_matches({}, "xxxx")
    assert not catalog_entry_matches({"tags": ["read-only"]}, "xx")
    # Present tokens match even when other tokens ("xx") are absent.
    assert catalog_entry_matches(
        {"tags": ["epsilon-tag", "zeta-tag"]},
        "epsilon-tag xx zeta-tag",
    )


def test_upstream_metadata_matching_indexes_identity_prefix_smoke_purpose_and_tags() -> None:
    # Distinct tokens per field so a single-token query isolates exactly one field;
    # if any field stops being indexed, its query stops matching.
    upstream = UpstreamConfig(
        name="alphaname",
        command="alphaname",
        tool_prefix="bravoprefix",
        purpose="charliepurpose graph",
        tags=("deltatag", "echotag"),
        smoke=SmokeProbe(
            query="foxtrotquery indexed",
            tool="golftool",
            arguments={},
        ),
    )

    assert upstream_metadata_matches(upstream, "alphaname")  # upstream name
    assert upstream_metadata_matches(upstream, "bravoprefix")  # tool prefix
    assert upstream_metadata_matches(upstream, "golftool")  # smoke tool name
    assert upstream_metadata_matches(upstream, "foxtrotquery")  # smoke query (description)
    assert upstream_metadata_matches(upstream, "charliepurpose")  # purpose
    assert upstream_metadata_matches(upstream, "deltatag")  # tag
    assert upstream_metadata_matches(upstream, "echotag")  # tag
    # A query whose tokens hit no field does not match.
    assert not upstream_metadata_matches(upstream, "nonexistent")


def test_upstream_metadata_matching_handles_missing_smoke_and_prefix_fallback() -> None:
    upstream = UpstreamConfig(
        name="notes-cache",
        command="notes-cache",
        tool_prefix=None,
        purpose="Persistent notes",
        tags=("context",),
    )

    assert upstream_metadata_matches(upstream, "notes-cache context")
    assert upstream_metadata_matches(upstream, "persistent notes")
    assert not upstream_metadata_matches(upstream, "list projects")
    assert not upstream_metadata_matches(upstream, "xxxx")


def test_upstream_metadata_matching_indexes_custom_prefix_without_smoke() -> None:
    upstream = UpstreamConfig(
        name="repo-index",
        command="repo-index",
        tool_prefix="codegraph",
        purpose="",
        tags=(),
    )

    assert upstream_metadata_matches(upstream, "codegraph")


def test_upstream_tool_name_matching_requires_prefix_and_separator() -> None:
    prefixed = UpstreamConfig(name="repo-index", command="repo-index", tool_prefix="repo")
    fallback = UpstreamConfig(name="notes-cache", command="notes-cache", tool_prefix=None)

    assert upstream_owns_tool_name(prefixed, "repo.list_projects", ".")
    assert upstream_owns_tool_name(fallback, "notes-cache__search", "__")
    assert not upstream_owns_tool_name(prefixed, "repo-index.list_projects", ".")
    assert not upstream_owns_tool_name(prefixed, "repo-list_projects", ".")
    assert not upstream_owns_tool_name(prefixed, "xrepo.list_projects", ".")


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", False),
        ("github", False),
        (" github ", False),
        ("github issue", True),
        ("  github   issue  ", True),
    ],
)
def test_specific_query_requires_at_least_two_tokens(query: str, expected: bool) -> None:
    assert _specific_query_can_select_upstream(query) is expected


def test_catalog_entries_use_prefix_schema_metadata_and_skip_nameless_tools() -> None:
    upstream = UpstreamConfig(
        name="work-store",
        command="work-store",
        tool_prefix="work",
        purpose="Search work records",
        tags=("records", "read-only"),
        mutating=True,
    )

    entries = catalog_entries_for_upstream(
        upstream,
        [
            {"description": "no tool name"},
            {
                "name": "lookup",
                "description": "Lookup a record",
                "inputSchema": {"type": "object", "required": ["id"]},
            },
            {"name": "health"},
        ],
        ".",
    )

    assert entries == [
        {
            "name": "work.lookup",
            "upstream": "work-store",
            "description": "Lookup a record",
            "inputSchema": {"type": "object", "required": ["id"]},
            "purpose": "Search work records",
            "tags": ["records", "read-only"],
            "mutating": True,
        },
        {
            "name": "work.health",
            "upstream": "work-store",
            "description": "",
            "inputSchema": {"type": "object"},
            "purpose": "Search work records",
            "tags": ["records", "read-only"],
            "mutating": True,
        },
    ]


def test_catalog_entries_fall_back_to_upstream_name_when_prefix_is_empty() -> None:
    upstream = UpstreamConfig(name="read-store", command="read-store", tool_prefix=None)

    entries = catalog_entries_for_upstream(upstream, [{"name": "read"}], "__")

    assert entries[0]["name"] == "read-store__read"
    assert entries[0]["upstream"] == "read-store"


def test_unavailable_catalog_entry_keeps_upstream_metadata() -> None:
    upstream = UpstreamConfig(
        name="remote-store",
        command="remote-store",
        purpose="Remote records",
        tags=("remote",),
        mutating=True,
    )

    assert catalog_unavailable_entry_for_upstream(upstream, "missing token") == {
        "name": "remote-store",
        "upstream": "remote-store",
        "description": "upstream unavailable: missing token",
        "purpose": "Remote records",
        "tags": ["remote"],
        "mutating": True,
        "available": False,
    }


def test_structured_tool_result_returns_exact_mcp_payload_shape() -> None:
    payload = {"z": 1, "a": 2}

    assert structured_tool_result(payload) == {
        "content": [
            {
                "type": "text",
                "text": '{"a": 2, "z": 1}',
            }
        ],
        "structuredContent": payload,
    }


def test_profile_allows_upstream_without_profile_or_with_matching_profile() -> None:
    upstream = UpstreamConfig(
        name="read-store",
        command="read-store",
        profiles=("default-llm",),
    )

    assert profile_allows_upstream(None, upstream)
    assert profile_allows_upstream(ToolExposureProfile(name="default-llm", max_tools=20), upstream)
    assert not profile_allows_upstream(ToolExposureProfile(name="other-llm", max_tools=20), upstream)


def test_search_tools_returns_limited_matches_and_skipped_upstreams(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)
    list_calls: list[tuple[str, int]] = []

    def list_upstream(upstream_name: str, timeout: int) -> list[dict[str, object]]:
        list_calls.append((upstream_name, timeout))
        if upstream_name == "broken-store":
            raise RuntimeError("missing runtime token")
        if upstream_name == "read-store":
            return [
                {"name": "find_record", "description": "Find a record"},
                {"name": "list_records", "description": "List records"},
            ]
        return [{"name": "ignored"}]

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=ToolExposureProfile(name="default-llm", max_tools=20),
        list_upstream=list_upstream,
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    ).call_tool("broker.search_tools", {"query": "record", "limit": "1"})

    assert result["structuredContent"] == {
        "matches": [
            {
                "name": "read.find_record",
                "upstream": "read-store",
                "description": "Find a record",
                "inputSchema": {"type": "object"},
                "purpose": "Read records",
                "tags": ["records"],
                "mutating": False,
            }
        ],
        "skipped_upstreams": {"broken-store": "missing runtime token"},
    }
    assert list_calls == [("read-store", 60), ("broken-store", 60)]
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]


def test_catalog_entries_requires_explicit_query_or_tool_name(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)
    facade = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [{"name": "find_record"}],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    )

    with pytest.raises(TypeError):
        facade._catalog_entries()  # type: ignore[call-arg]


def test_catalog_entries_rejects_invalid_selector_modes(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)
    facade = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [{"name": "find_record"}],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    )

    with pytest.raises(TypeError) as query_type_error:
        facade._catalog_entries(query="record", tool_name=None)  # type: ignore[arg-type]
    assert str(query_type_error.value) == "query and tool_name must be strings"

    with pytest.raises(TypeError) as tool_name_type_error:
        facade._catalog_entries(query=None, tool_name="read.find_record")  # type: ignore[arg-type]
    assert str(tool_name_type_error.value) == "query and tool_name must be strings"

    with pytest.raises(ValueError) as double_selector_error:
        facade._catalog_entries(query="record", tool_name="read.find_record")
    assert str(double_selector_error.value) == "use query or tool_name, not both"


def test_catalog_upstreams_requires_explicit_query_or_tool_name(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)
    facade = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [{"name": "find_record"}],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    )

    with pytest.raises(TypeError):
        facade._catalog_upstreams()  # type: ignore[call-arg]


def test_search_tools_defaults_to_empty_query_and_twenty_results(tmp_path: Path) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"default-llm": ToolExposureProfile(name="default-llm", max_tools=30)},
        upstreams={
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                tool_prefix="read",
                profiles=("default-llm",),
            )
        },
    )

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [
            {"name": f"tool_{index:02d}", "description": f"Tool {index:02d}"}
            for index in range(21)
        ],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    ).call_tool("broker.search_tools", {})

    names = [match["name"] for match in result["structuredContent"]["matches"]]
    assert names == [f"read.tool_{index:02d}" for index in range(20)]


def test_search_tools_uses_upstream_metadata_to_avoid_slow_irrelevant_listing(
    tmp_path: Path,
) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"codex": ToolExposureProfile(name="codex", max_tools=80)},
        upstreams={
            "notes-cache": UpstreamConfig(
                name="notes-cache",
                command="notes-cache",
                tool_prefix="notes-cache",
                profiles=("codex",),
                purpose="Persistent project notes and cross-session context.",
                tags=("notes", "context", "project-context"),
            ),
            "repo-index": UpstreamConfig(
                name="repo-index",
                command="repo-index",
                tool_prefix="repo-index",
                profiles=("codex",),
                purpose="Codebase graph exploration, architecture lookup, and call tracing.",
                tags=("codebase", "graph", "architecture", "tracing"),
                smoke=SmokeProbe(
                    query="list indexed codebase projects",
                    tool="repo-index.list_projects",
                    arguments={},
                ),
            ),
        },
    )
    list_calls: list[str] = []

    def list_upstream(upstream_name: str, _timeout: int) -> list[dict[str, object]]:
        list_calls.append(upstream_name)
        if upstream_name == "notes-cache":
            raise RuntimeError("notes-cache should not be listed for this query")
        return [{"name": "list_projects", "description": "List indexed projects"}]

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["codex"],
        list_upstream=list_upstream,
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    ).call_tool("broker.search_tools", {"query": "list indexed codebase projects"})

    assert list_calls == ["repo-index"]
    assert [match["name"] for match in result["structuredContent"]["matches"]] == [
        "repo-index.list_projects"
    ]


def test_search_tools_keeps_all_upstreams_for_single_token_queries(tmp_path: Path) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"codex": ToolExposureProfile(name="codex", max_tools=80)},
        upstreams={
            "notes-cache": UpstreamConfig(
                name="notes-cache",
                command="notes-cache",
                tool_prefix="notes",
                profiles=("codex",),
                purpose="Persistent project notes",
                tags=("context",),
            ),
            "repo-index": UpstreamConfig(
                name="repo-index",
                command="repo-index",
                tool_prefix="repo",
                profiles=("codex",),
                purpose="Codebase graph exploration",
                tags=("codebase",),
            ),
        },
    )
    list_calls: list[str] = []

    BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["codex"],
        list_upstream=lambda name, _timeout: list_calls.append(name) or [{"name": "search"}],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    ).call_tool("broker.search_tools", {"query": "codebase"})

    assert list_calls == ["notes-cache", "repo-index"]


def test_search_tools_falls_back_to_all_upstreams_when_metadata_has_no_match(
    tmp_path: Path,
) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"codex": ToolExposureProfile(name="codex", max_tools=80)},
        upstreams={
            "notes-cache": UpstreamConfig(
                name="notes-cache",
                command="notes-cache",
                tool_prefix="notes",
                profiles=("codex",),
                purpose="Persistent project notes",
                tags=("context",),
            ),
            "repo-index": UpstreamConfig(
                name="repo-index",
                command="repo-index",
                tool_prefix="repo",
                profiles=("codex",),
                purpose="Codebase graph exploration",
                tags=("codebase",),
            ),
        },
    )
    list_calls: list[str] = []

    BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["codex"],
        list_upstream=lambda name, _timeout: list_calls.append(name) or [{"name": "search"}],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    ).call_tool("broker.search_tools", {"query": "calendar event"})

    assert list_calls == ["notes-cache", "repo-index"]


def test_describe_tool_returns_exact_catalog_entry_and_rejects_bad_names(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)
    facade = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [{"name": "find_record", "description": "Find"}],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    )

    described = facade.call_tool("broker.describe_tool", {"name": "read.find_record"})

    assert described["structuredContent"]["tool"]["name"] == "read.find_record"
    assert described["structuredContent"]["tool"]["description"] == "Find"
    with pytest.raises(ValueError, match="requires string name"):
        facade.call_tool("broker.describe_tool", {"name": 123})
    with pytest.raises(ValueError, match="broker tool not found"):
        facade.call_tool("broker.describe_tool", {"name": "read.missing"})


def test_describe_tool_uses_tool_prefix_to_avoid_slow_irrelevant_listing(
    tmp_path: Path,
) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"codex": ToolExposureProfile(name="codex", max_tools=80)},
        upstreams={
            "notes-cache": UpstreamConfig(
                name="notes-cache",
                command="notes-cache",
                tool_prefix="notes-cache",
                profiles=("codex",),
            ),
            "repo-index": UpstreamConfig(
                name="repo-index",
                command="repo-index",
                tool_prefix="repo-index",
                profiles=("codex",),
            ),
        },
    )
    list_calls: list[str] = []

    def list_upstream(upstream_name: str, _timeout: int) -> list[dict[str, object]]:
        list_calls.append(upstream_name)
        if upstream_name == "notes-cache":
            raise RuntimeError("notes-cache should not be listed for this tool")
        return [{"name": "list_projects", "description": "List indexed projects"}]

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["codex"],
        list_upstream=list_upstream,
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    ).call_tool("broker.describe_tool", {"name": "repo-index.list_projects"})

    assert list_calls == ["repo-index"]
    assert result["structuredContent"]["tool"]["name"] == "repo-index.list_projects"


def test_describe_tool_falls_back_to_all_upstreams_for_unknown_prefix(
    tmp_path: Path,
) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"codex": ToolExposureProfile(name="codex", max_tools=80)},
        upstreams={
            "notes-cache": UpstreamConfig(
                name="notes-cache",
                command="notes-cache",
                tool_prefix="notes",
                profiles=("codex",),
            ),
            "repo-index": UpstreamConfig(
                name="repo-index",
                command="repo-index",
                tool_prefix="repo",
                profiles=("codex",),
            ),
        },
    )
    list_calls: list[str] = []

    facade = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["codex"],
        list_upstream=lambda name, _timeout: list_calls.append(name) or [{"name": "search"}],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    )

    with pytest.raises(ValueError, match="broker tool not found"):
        facade.call_tool("broker.describe_tool", {"name": "unknown.search"})

    assert list_calls == ["notes-cache", "repo-index"]


def test_call_tool_accepts_profile_snake_aliases(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)
    profile = ToolExposureProfile(
        name="default-llm",
        max_tools=20,
        broker_tool_name_style="snake",
    )

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=profile,
        list_upstream=lambda _name, _timeout: [{"name": "find_record", "description": "Find"}],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    ).call_tool("broker_search_tools", {"query": "find"})

    match_names = [match["name"] for match in result["structuredContent"]["matches"]]
    assert "read.find_record" in match_names


def test_search_tools_ranks_name_matches_above_description_matches(tmp_path: Path) -> None:
    config = BrokerConfig(
        runtime=RuntimeConfig(
            root=tmp_path,
            socket_path=tmp_path / "s.sock",
            log_dir=tmp_path / "logs",
            state_dir=tmp_path / "state",
            secrets_dir=tmp_path / "secrets",
        ),
        broker=BrokerSettings(),
        profiles={"llm": ToolExposureProfile(name="llm", max_tools=20)},
        upstreams={
            "alpha": UpstreamConfig(name="alpha", command="alpha", tool_prefix="a", profiles=("llm",)),
            "beta": UpstreamConfig(name="beta", command="beta", tool_prefix="b", profiles=("llm",)),
        },
    )

    def list_upstream(name: str, _timeout: int) -> list[dict[str, object]]:
        if name == "alpha":
            return [{"name": "deploy_app", "description": "unrelated text"}]  # name hit -> high score
        return [{"name": "run", "description": "deploy the app"}]  # description hit -> low score

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["llm"],
        list_upstream=list_upstream,
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    ).call_tool("broker.search_tools", {"query": "deploy"})

    names = [match["name"] for match in result["structuredContent"]["matches"]]
    # Name match (a.deploy_app) outranks the description-only match (b.run).
    assert names == ["a.deploy_app", "b.run"]


def test_call_tool_unknown_broker_tool_raises_contract_error(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)
    facade = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    )

    with pytest.raises(BrokerToolError) as exc:
        facade.call_tool("broker.missing", {})

    assert exc.value.code == "unknown_broker_tool"
    assert exc.value.message == "unknown broker tool: broker.missing"


def test_call_managed_tool_rejects_invalid_payload_before_upstream_call(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)
    calls: list[tuple[str, str, dict[str, object], int]] = []

    facade = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda name, tool, args, timeout: calls.append((name, tool, args, timeout)) or {},
        call_locks={},
    )

    with pytest.raises(ValueError, match="requires name and object arguments"):
        facade.call_tool("broker.call_tool", {"name": "read.find_record", "arguments": []})
    with pytest.raises(ValueError, match="requires name and object arguments"):
        facade.call_tool("broker.call_tool", {"name": None, "arguments": {}})
    assert calls == []


def test_call_managed_tool_defaults_missing_arguments_to_empty_object(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)
    calls: list[tuple[str, str, dict[str, object], int]] = []

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda name, tool, args, timeout: calls.append((name, tool, args, timeout))
        or {"content": []},
        call_locks={},
    ).call_tool("broker.call_tool", {"name": "read.find_record"})

    assert result == {"content": []}
    assert calls == [("read-store", "find_record", {}, 60)]


def test_call_managed_tool_enforces_profile_and_uses_shared_call_locks(tmp_path: Path) -> None:
    profile = ToolExposureProfile(name="default-llm", max_tools=20)
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={},
        upstreams={
            "write-store": UpstreamConfig(
                name="write-store",
                command="write-store",
                tool_prefix="write",
                profiles=("default-llm",),
                mutating=True,
                serialize_calls=True,
            ),
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                tool_prefix="read",
                profiles=("default-llm",),
                serialize_calls=True,
            ),
        },
    )
    call_locks: dict[str, object] = {}
    calls: list[tuple[str, str, dict[str, object], int]] = []
    facade = BrokerCatalogFacade(
        broker_config=config,
        profile=profile,
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda name, tool, args, timeout: calls.append((name, tool, args, timeout))
        or {"content": []},
        call_locks=call_locks,  # type: ignore[arg-type]
    )

    with pytest.raises(BrokerToolError) as exc:
        facade.call_tool("broker.call_tool", {"name": "write.create", "arguments": {}})

    assert exc.value.code == "mutating_not_allowed"
    assert calls == []
    assert facade.call_tool("broker.call_tool", {"name": "read.find", "arguments": {}}) == {
        "content": []
    }
    assert calls == [("read-store", "find", {}, 60)]
    assert set(call_locks) == {"read-store"}


def test_status_reports_visible_disabled_and_allowed_mutating_upstreams(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)
    profile = ToolExposureProfile(
        name="default-llm",
        max_tools=20,
        allow_mutating_upstreams=("write-store",),
    )
    visible_sets: list[set[str] | None] = []

    def status_provider(visible: set[str] | None) -> dict[str, dict[str, object]]:
        visible_sets.append(visible)
        return {
            "read-store": {
                "state": "running",
                "pid": 456,
                "restarts": 2,
                "sessions": 3,
                "auth_probe": "tool-call",
                "auth_state": "authenticated",
                "auth_repair_attempts": 4,
                "auth_repair_successes": 3,
                "auth_repair_failures": 1,
            },
            "write-store": {
                "state": "running",
                "auth_state": "unauthenticated",
                "last_error": "token expired",
            },
            "broken-store": {
                "state": "configured",
                "auth_state": "invalid-value",
                "last_error": "HTTP 403 forbidden",
            },
            "disabled-store": {"state": "disabled"},
        }

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=profile,
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
        status_provider=status_provider,
    ).call_tool("broker.status", {})

    payload = result["structuredContent"]
    assert visible_sets == [{"read-store", "write-store", "broken-store"}]
    assert payload["profile"] == "default-llm"
    assert payload["socket_path"] == str(config.runtime.socket_path)
    assert payload["status"] == "degraded"
    assert set(payload["upstreams"]) == {
        "read-store",
        "write-store",
        "broken-store",
        "disabled-store",
    }
    assert payload["upstreams"]["read-store"] == {
        "enabled": True,
        "auth_repair_attempts": 4,
        "auth_repair_failures": 1,
        "auth_repair_successes": 3,
        "auth_probe": "tool-call",
        "auth_state": "authenticated",
        "exposed": True,
        "last_error": None,
        "mode": "shared",
        "mutating": False,
        "pid": 456,
        "restarts": 2,
        "session_count": 3,
        "state": "running",
        "transport": "stdio",
    }
    assert payload["upstreams"]["write-store"]["auth_state"] == "unauthenticated"
    assert payload["upstreams"]["write-store"]["mutating"] is True
    assert payload["upstreams"]["broken-store"]["auth_state"] == "unauthenticated"
    assert payload["upstreams"]["disabled-store"]["enabled"] is False
    assert payload["upstreams"]["disabled-store"]["exposed"] is False
    assert payload["upstreams"]["disabled-store"]["state"] == "disabled"


def test_status_reports_session_count_key_and_default_configured_states(tmp_path: Path) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"default-llm": ToolExposureProfile(name="default-llm", max_tools=20)},
        upstreams={
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                profiles=("default-llm",),
            ),
            "mode-disabled-store": UpstreamConfig(
                name="mode-disabled-store",
                command="mode-disabled-store",
                mode="disabled",
                profiles=("default-llm",),
            ),
        },
    )

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
        status_provider=lambda _visible: {"read-store": {"session_count": 7}},
    ).call_tool("broker.status", {})

    payload = result["structuredContent"]
    assert payload["socket_path"] == str(config.runtime.socket_path)
    assert payload["status"] == "ok"
    assert payload["upstreams"]["read-store"]["session_count"] == 7
    assert payload["upstreams"]["read-store"]["state"] == "configured"
    assert payload["upstreams"]["mode-disabled-store"]["enabled"] is True
    assert payload["upstreams"]["mode-disabled-store"]["exposed"] is False
    assert payload["upstreams"]["mode-disabled-store"]["state"] == "disabled"


@pytest.mark.parametrize("state", ["exited", "failed", "backoff"])
def test_status_degrades_for_stopped_runtime_states(tmp_path: Path, state: str) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"default-llm": ToolExposureProfile(name="default-llm", max_tools=20)},
        upstreams={
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                profiles=("default-llm",),
            )
        },
    )

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
        status_provider=lambda _visible: {"read-store": {"state": state}},
    ).call_tool("broker.status", {})

    assert result["structuredContent"]["status"] == "degraded"
    assert result["structuredContent"]["upstreams"]["read-store"]["last_error"] is None


def test_status_filters_enabled_upstreams_hidden_by_profile_or_mutating_policy(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=ToolExposureProfile(name="default-llm", max_tools=20),
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
        status_provider=lambda visible: {name: {"state": "running"} for name in visible or set()},
    ).call_tool("broker.status", {})

    payload = result["structuredContent"]
    assert set(payload["upstreams"]) == {"read-store", "broken-store", "disabled-store"}
    assert "write-store" not in payload["upstreams"]
    assert "other-profile-store" not in payload["upstreams"]


def test_status_rejects_arguments_except_client_control(tmp_path: Path) -> None:
    config = _catalog_config(tmp_path)
    facade = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    )

    assert facade.call_tool("broker.status", {"wait_for_previous": True})["structuredContent"][
        "profile"
    ] == "default-llm"
    with pytest.raises(ValueError) as exc:
        facade.call_tool("broker.status", {"verbose": True})

    assert str(exc.value) == "broker.status does not accept arguments"


def test_catalog_listing_continues_after_unavailable_and_disabled_upstreams(
    tmp_path: Path,
) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"default-llm": ToolExposureProfile(name="default-llm", max_tools=20)},
        upstreams={
            "mode-disabled-store": UpstreamConfig(
                name="mode-disabled-store",
                command="mode-disabled-store",
                mode="disabled",
                profiles=("default-llm",),
            ),
            "broken-store": UpstreamConfig(
                name="broken-store",
                command="broken-store",
                profiles=("default-llm",),
            ),
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                tool_prefix="read",
                profiles=("default-llm",),
            ),
        },
    )
    calls: list[str] = []

    def list_upstream(upstream_name: str, _timeout: int) -> list[dict[str, object]]:
        calls.append(upstream_name)
        if upstream_name == "broken-store":
            raise RuntimeError("missing token")
        return [{"name": "find"}]

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=list_upstream,
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    ).call_tool("broker.search_tools", {"query": ""})

    assert calls == ["broken-store", "read-store"]
    assert [match["name"] for match in result["structuredContent"]["matches"]] == [
        "broken-store",
        "read.find",
    ]
    assert result["structuredContent"]["skipped_upstreams"] == {
        "broken-store": "missing token"
    }


def test_catalog_listing_continues_after_profile_hidden_upstream(tmp_path: Path) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={
            "default-llm": ToolExposureProfile(
                name="default-llm",
                max_tools=20,
                allow_mutating_upstreams=("write-store",),
            ),
            "other-llm": ToolExposureProfile(name="other-llm", max_tools=20),
        },
        upstreams={
            "other-profile-store": UpstreamConfig(
                name="other-profile-store",
                command="other-profile-store",
                profiles=("other-llm",),
            ),
            "write-store": UpstreamConfig(
                name="write-store",
                command="write-store",
                tool_prefix="write",
                profiles=("default-llm",),
                mutating=True,
            ),
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                tool_prefix="read",
                profiles=("default-llm",),
            ),
        },
    )
    calls: list[str] = []

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda name, _timeout: calls.append(name) or [{"name": "tool"}],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
    ).call_tool("broker.search_tools", {"query": ""})

    assert calls == ["write-store", "read-store"]
    # Empty query scores all entries equally, so matches are ordered by name (asc).
    assert [match["name"] for match in result["structuredContent"]["matches"]] == [
        "read.tool",
        "write.tool",
    ]


@pytest.mark.parametrize(
    ("last_error", "expected_state"),
    [
        ("auth failed", "unauthenticated"),
        ("missing credential", "unauthenticated"),
        ("forbidden by provider", "unauthenticated"),
        ("bad token", "unauthenticated"),
        ("unauthorized request", "unauthenticated"),
        ("HTTP 401", "unauthenticated"),
        ("HTTP 403", "unauthenticated"),
        ("missing DISPLAY", "unknown"),
        (None, "unknown"),
    ],
)
def test_status_infers_auth_state_from_last_error(
    tmp_path: Path,
    last_error: str | None,
    expected_state: str,
) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"default-llm": ToolExposureProfile(name="default-llm", max_tools=20)},
        upstreams={
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                profiles=("default-llm",),
            )
        },
    )

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
        status_provider=lambda _visible: {"read-store": {"last_error": last_error}},
    ).call_tool("broker.status", {})

    assert result["structuredContent"]["upstreams"]["read-store"]["auth_state"] == expected_state


@pytest.mark.parametrize("auth_state", ["authenticated", "unauthenticated", "unknown"])
def test_status_preserves_explicit_auth_state_values(
    tmp_path: Path,
    auth_state: str,
) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"default-llm": ToolExposureProfile(name="default-llm", max_tools=20)},
        upstreams={
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                profiles=("default-llm",),
            )
        },
    )

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
        status_provider=lambda _visible: {
            "read-store": {
                "auth_state": auth_state,
                "last_error": "display unavailable",
            }
        },
    ).call_tool("broker.status", {})

    assert result["structuredContent"]["upstreams"]["read-store"]["auth_state"] == auth_state


def test_status_preserves_explicit_unknown_auth_state_over_auth_looking_errors(
    tmp_path: Path,
) -> None:
    config = BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={"default-llm": ToolExposureProfile(name="default-llm", max_tools=20)},
        upstreams={
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                profiles=("default-llm",),
            )
        },
    )

    result = BrokerCatalogFacade(
        broker_config=config,
        profile=config.profiles["default-llm"],
        list_upstream=lambda _name, _timeout: [],
        call_upstream=lambda _name, _tool, _args, _timeout: {"content": []},
        call_locks={},
        status_provider=lambda _visible: {
            "read-store": {
                "auth_state": "unknown",
                "last_error": "HTTP 403 forbidden",
            }
        },
    ).call_tool("broker.status", {})

    assert result["structuredContent"]["upstreams"]["read-store"]["auth_state"] == "unknown"


def _catalog_config(tmp_path: Path) -> BrokerConfig:
    return BrokerConfig(
        runtime=_runtime(tmp_path),
        broker=BrokerSettings(),
        profiles={
            "default-llm": ToolExposureProfile(
                name="default-llm",
                max_tools=20,
                compact_tools_enabled=True,
                allow_mutating_upstreams=("write-store",),
            ),
            "other-llm": ToolExposureProfile(name="other-llm", max_tools=20),
        },
        upstreams={
            "read-store": UpstreamConfig(
                name="read-store",
                command="read-store",
                tool_prefix="read",
                profiles=("default-llm",),
                purpose="Read records",
                tags=("records",),
            ),
            "write-store": UpstreamConfig(
                name="write-store",
                command="write-store",
                tool_prefix="write",
                profiles=("default-llm",),
                mutating=True,
            ),
            "broken-store": UpstreamConfig(
                name="broken-store",
                command="broken-store",
                profiles=("default-llm",),
            ),
            "other-profile-store": UpstreamConfig(
                name="other-profile-store",
                command="other-profile-store",
                profiles=("other-llm",),
            ),
            "disabled-store": UpstreamConfig(
                name="disabled-store",
                command="disabled-store",
                enabled=False,
                profiles=("default-llm",),
            ),
        },
    )


def _runtime(tmp_path: Path) -> RuntimeConfig:
    return RuntimeConfig(
        root=tmp_path / "runtime",
        socket_path=tmp_path / "runtime" / "sockets" / "broker.sock",
        log_dir=tmp_path / "runtime" / "logs",
        state_dir=tmp_path / "runtime" / "state",
        secrets_dir=tmp_path / "runtime" / "secrets",
    )
