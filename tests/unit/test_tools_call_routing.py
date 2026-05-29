import pytest
import threading
from concurrent.futures import ThreadPoolExecutor


pytestmark = pytest.mark.unit


def test_broker_call_tool_routes_namespaced_tool_to_upstream() -> None:
    from mcp_broker.broker import BrokerCore
    from mcp_broker.config import BrokerSettings
    from mcp_broker.profiles import ToolExposureProfile

    caller = RecordingCaller({"content": [{"type": "text", "text": "found"}]})
    broker = BrokerCore(
        settings=BrokerSettings(tool_namespace_separator="."),
        upstreams=_upstreams(),
        profile=ToolExposureProfile(name="llm", max_tools=10),
    )

    result = broker.call_tool("read-store.search", {"query": "refund"}, caller)

    assert result == {"content": [{"type": "text", "text": "found"}]}
    assert caller.calls == [("read-store", "search", {"query": "refund"}, 7)]


def test_broker_call_tool_uses_configured_per_tool_timeout() -> None:
    from mcp_broker.broker import BrokerCore
    from mcp_broker.config import BrokerSettings, UpstreamConfig
    from mcp_broker.profiles import ToolExposureProfile
    from mcp_broker.schema import HealthPolicy

    caller = RecordingCaller({"content": [{"type": "text", "text": "drafted"}]})
    broker = BrokerCore(
        settings=BrokerSettings(tool_namespace_separator="."),
        upstreams={
            "mail-writer": UpstreamConfig(
                name="mail-writer",
                command="ms365",
                tool_prefix="mail-writer",
                profiles=("protected",),
                health=HealthPolicy(call_timeout_seconds=60),
                tool_timeouts={"create-draft-email": 300},
            )
        },
        profile=ToolExposureProfile(
            name="protected",
            max_tools=10,
            allow_mutating_upstreams=("mail-writer",),
        ),
    )

    result = broker.call_tool(
        "mail-writer.create-draft-email",
        {"subject": "large draft"},
        caller,
    )

    assert result == {"content": [{"type": "text", "text": "drafted"}]}
    assert caller.calls == [
        ("mail-writer", "create-draft-email", {"subject": "large draft"}, 300)
    ]


def test_broker_call_tool_uses_default_timeout_when_tool_has_no_override() -> None:
    from mcp_broker.broker import BrokerCore
    from mcp_broker.config import BrokerSettings, UpstreamConfig
    from mcp_broker.profiles import ToolExposureProfile
    from mcp_broker.schema import HealthPolicy

    caller = RecordingCaller({"content": [{"type": "text", "text": "ok"}]})
    broker = BrokerCore(
        settings=BrokerSettings(tool_namespace_separator="."),
        upstreams={
            "mail-writer": UpstreamConfig(
                name="mail-writer",
                command="ms365",
                tool_prefix="mail-writer",
                profiles=("protected",),
                health=HealthPolicy(call_timeout_seconds=60),
                tool_timeouts={"create-draft-email": 300},
            )
        },
        profile=ToolExposureProfile(
            name="protected",
            max_tools=10,
            allow_mutating_upstreams=("mail-writer",),
        ),
    )

    result = broker.call_tool("mail-writer.verify-login", {}, caller)

    assert result == {"content": [{"type": "text", "text": "ok"}]}
    assert caller.calls == [("mail-writer", "verify-login", {}, 60)]


def test_broker_call_tool_rejects_invalid_arguments() -> None:
    from mcp_broker.broker import BrokerCore, BrokerToolError
    from mcp_broker.config import BrokerSettings
    from mcp_broker.profiles import ToolExposureProfile

    broker = BrokerCore(
        settings=BrokerSettings(tool_namespace_separator="."),
        upstreams=_upstreams(),
        profile=ToolExposureProfile(name="llm", max_tools=10),
    )
    caller = RecordingCaller({"content": []})

    with pytest.raises(BrokerToolError) as exc:
        broker.call_tool("read-store.search", ["bad"], caller)

    assert exc.value.code == "invalid_arguments"
    assert exc.value.message == "tools/call arguments must be an object"
    assert caller.calls == []


def test_broker_call_tool_rejects_unknown_disabled_and_profile_denied_prefixes() -> None:
    from mcp_broker.broker import BrokerCore, BrokerToolError
    from mcp_broker.config import BrokerSettings
    from mcp_broker.profiles import ToolExposureProfile

    broker = BrokerCore(
        settings=BrokerSettings(tool_namespace_separator="."),
        upstreams=_upstreams(),
        profile=ToolExposureProfile(name="llm", max_tools=10),
    )
    caller = RecordingCaller({"content": []})

    with pytest.raises(BrokerToolError) as unknown_exc:
        broker.call_tool("missing.search", {}, caller)
    assert unknown_exc.value.code == "unknown_tool_prefix"
    assert unknown_exc.value.message == "unknown tool prefix: missing"

    with pytest.raises(BrokerToolError) as disabled_exc:
        broker.call_tool("disabled.hidden", {}, caller)
    assert disabled_exc.value.code == "disabled_prefix"
    assert disabled_exc.value.message == "tool prefix disabled: disabled"

    with pytest.raises(BrokerToolError) as denied_exc:
        broker.call_tool("mail-writer.create_draft", {}, caller)
    assert denied_exc.value.code == "profile_denied"
    assert denied_exc.value.message == "tool prefix denied for profile llm: mail-writer"

    assert caller.calls == []


def test_broker_call_tool_rejects_mutating_upstream_without_profile_allowlist() -> None:
    from mcp_broker.broker import BrokerCore, BrokerToolError
    from mcp_broker.config import BrokerSettings, UpstreamConfig
    from mcp_broker.profiles import ToolExposureProfile

    broker = BrokerCore(
        settings=BrokerSettings(tool_namespace_separator="."),
        upstreams={
            "workspace-writer": UpstreamConfig(
                name="workspace-writer",
                command="gws",
                args=["mcp"],
                mode="per_session",
                enabled=True,
                tool_prefix="workspace-writer",
                profiles=("protected",),
                mutating=True,
            )
        },
        profile=ToolExposureProfile(name="protected", max_tools=10),
    )
    caller = RecordingCaller({"content": []})

    with pytest.raises(BrokerToolError) as exc:
        broker.call_tool("workspace-writer.create_document", {}, caller)

    assert exc.value.code == "mutating_not_allowed"
    assert exc.value.message == "mutating upstream not allowed for profile protected: workspace-writer"
    assert caller.calls == []


def test_broker_call_tool_rejects_malformed_tool_names() -> None:
    from mcp_broker.broker import BrokerCore, BrokerToolError
    from mcp_broker.config import BrokerSettings
    from mcp_broker.profiles import ToolExposureProfile

    broker = BrokerCore(
        settings=BrokerSettings(tool_namespace_separator="."),
        upstreams=_upstreams(),
        profile=ToolExposureProfile(name="llm", max_tools=10),
    )
    caller = RecordingCaller({"content": []})

    with pytest.raises(BrokerToolError) as missing_separator:
        broker.call_tool("search", {}, caller)
    assert missing_separator.value.code == "invalid_tool_name"
    assert missing_separator.value.message == "missing namespace separator: search"

    with pytest.raises(BrokerToolError) as missing_tool:
        broker.call_tool("read-store.", {}, caller)
    assert missing_tool.value.code == "invalid_tool_name"
    assert missing_tool.value.message == "missing upstream tool name: read-store."

    assert caller.calls == []


def test_broker_call_tool_maps_upstream_failures() -> None:
    from mcp_broker.broker import (
        BrokerCore,
        BrokerToolError,
        UpstreamCallCrashed,
        UpstreamCallTimeout,
        UpstreamToolNotFound,
    )
    from mcp_broker.config import BrokerSettings
    from mcp_broker.profiles import ToolExposureProfile

    broker = BrokerCore(
        settings=BrokerSettings(tool_namespace_separator="."),
        upstreams=_upstreams(),
        profile=ToolExposureProfile(name="llm", max_tools=10),
    )

    cases = [
        (UpstreamCallTimeout("timed out"), "upstream_timeout", "upstream timed out: read-store"),
        (UpstreamCallCrashed("exited"), "upstream_crashed", "upstream crashed: read-store"),
        (UpstreamToolNotFound("gone"), "unknown_upstream_tool", "upstream tool not found: read-store.search"),
    ]
    for raised, code, message in cases:
        with pytest.raises(BrokerToolError) as exc:
            broker.call_tool("read-store.search", {}, RaisingCaller(raised))
        assert exc.value.code == code
        assert exc.value.message == message
        assert exc.value.upstream_name == "read-store"
        assert exc.value.tool_name == "search"


def test_broker_call_tool_rejects_invalid_upstream_response() -> None:
    from mcp_broker.broker import BrokerCore, BrokerToolError
    from mcp_broker.config import BrokerSettings
    from mcp_broker.profiles import ToolExposureProfile

    broker = BrokerCore(
        settings=BrokerSettings(tool_namespace_separator="."),
        upstreams=_upstreams(),
        profile=ToolExposureProfile(name="llm", max_tools=10),
    )

    with pytest.raises(BrokerToolError) as exc:
        broker.call_tool("read-store.search", {}, RecordingCaller({"notContent": []}))

    assert exc.value.code == "invalid_upstream_response"
    assert exc.value.message == "invalid upstream tools/call response from read-store"


def test_broker_call_tool_serializes_configured_upstream_calls() -> None:
    from mcp_broker.broker import BrokerCore
    from mcp_broker.config import BrokerSettings, UpstreamConfig
    from mcp_broker.profiles import ToolExposureProfile

    upstreams = {
        "notes-writer": UpstreamConfig(
            name="notes-writer",
            command="notes-writer",
            mode="shared",
            enabled=True,
            tool_prefix="notes-writer",
            profiles=("protected",),
            serialize_calls=True,
        )
    }
    broker = BrokerCore(
        settings=BrokerSettings(tool_namespace_separator="."),
        upstreams=upstreams,
        profile=ToolExposureProfile(name="protected", max_tools=10),
    )
    caller = OverlapTrackingCaller()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(broker.call_tool, "notes-writer.write", {"n": 1}, caller)
        second = executor.submit(broker.call_tool, "notes-writer.write", {"n": 2}, caller)
        caller.start.set()

        assert first.result(timeout=2) == {"content": []}
        assert second.result(timeout=2) == {"content": []}

    assert caller.max_active == 1
    assert caller.calls == [
        ("notes-writer", "write", {"n": 1}, 60),
        ("notes-writer", "write", {"n": 2}, 60),
    ]


class RecordingCaller:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def __call__(self, upstream_name, tool_name, arguments, timeout_seconds):
        self.calls.append((upstream_name, tool_name, arguments, timeout_seconds))
        return self._response


class RaisingCaller:
    def __init__(self, raised):
        self._raised = raised

    def __call__(self, upstream_name, tool_name, arguments, timeout_seconds):
        raise self._raised


class OverlapTrackingCaller:
    def __init__(self):
        self.start = threading.Event()
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = []

    def __call__(self, upstream_name, tool_name, arguments, timeout_seconds):
        self.start.wait(timeout=1)
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append((upstream_name, tool_name, arguments, timeout_seconds))
        threading.Event().wait(timeout=0.05)
        with self._lock:
            self.active -= 1
        return {"content": []}


def _upstreams():
    from mcp_broker.config import UpstreamConfig
    from mcp_broker.schema import HealthPolicy

    return {
        "read-store": UpstreamConfig(
            name="read-store",
            command="read-store",
            args=[],
            mode="shared",
            enabled=True,
            tool_prefix="read-store",
            profiles=("llm", "maintenance"),
            health=HealthPolicy(call_timeout_seconds=7),
        ),
        "mail-writer": UpstreamConfig(
            name="mail-writer",
            command="ms365",
            args=[],
            mode="per_session",
            enabled=True,
            tool_prefix="mail-writer",
            profiles=("protected", "maintenance"),
        ),
        "disabled": UpstreamConfig(
            name="disabled",
            command="disabled",
            args=[],
            mode="disabled",
            enabled=True,
            tool_prefix="disabled",
            profiles=("llm",),
        ),
    }
