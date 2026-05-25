import io
import os
from pathlib import Path
import signal
import subprocess
import sys
from typing import Any, cast

import pytest

from mcp_broker.config import UpstreamConfig
from mcp_broker.upstream_stdio import (
    StdioUpstreamError,
    StdioUpstreamProcess,
    StdioUpstreamTimeout,
    _start_stderr_drainer,
)


pytestmark = pytest.mark.unit


def test_stdio_upstream_reuses_process_and_writes_stderr(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "echo_worker.py",
        """
import json
import os
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(f"stderr:{request['id']}", file=sys.stderr, flush=True)
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": {
            "cwd": os.getcwd(),
            "state": os.environ["MCP_BROKER_UPSTREAM_STATE_DIR"],
            "tool": request["params"]["name"],
            "arguments": request["params"]["arguments"],
        },
    }), flush=True)
""",
    )
    absolute_state_dir = tmp_path / "absolute-state"
    upstream = UpstreamConfig(
        name="fake",
        command=sys.executable,
        args=[str(script)],
        state_dir=str(absolute_state_dir),
    )
    client = StdioUpstreamProcess(upstream, runtime_state_dir=tmp_path / "runtime-state")

    try:
        first = client.call_tool("fake.echo", {"message": "first"}, timeout_seconds=1)
        pid = cast(subprocess.Popen[bytes], client._process).pid
        second = client.call_tool("fake.echo", {"message": "second"}, timeout_seconds=1)

        assert first["cwd"] == str(absolute_state_dir)
        assert first["state"] == str(absolute_state_dir)
        assert first["tool"] == "fake.echo"
        assert first["arguments"] == {"message": "first"}
        assert second["arguments"] == {"message": "second"}
        assert cast(subprocess.Popen[bytes], client._process).pid == pid
    finally:
        client.stop()

    assert "stderr:0" in (absolute_state_dir / "stderr.log").read_text(encoding="utf-8")


def test_stdio_stderr_drainer_stops_when_stream_is_already_closed(tmp_path: Path) -> None:
    stream = io.BytesIO(b"")
    stream.close()
    log_path = tmp_path / "stderr.log"

    thread = _start_stderr_drainer(stream, log_path)
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert log_path.read_bytes() == b""


def test_stdio_upstream_injects_configured_request_meta(tmp_path: Path) -> None:
    token_file = tmp_path / "token"
    token_file.write_text("request-token\n", encoding="utf-8")
    script = _script(
        tmp_path,
        "meta_worker.py",
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": {
            "meta": request["params"].get("_meta", {}),
        },
    }), flush=True)
""",
    )
    upstream = UpstreamConfig(
        name="notebook",
        command=sys.executable,
        args=[str(script)],
        env_files={"NLMCP_AUTH_TOKEN": token_file},
        request_meta={"authToken": "NLMCP_AUTH_TOKEN"},
    )
    client = StdioUpstreamProcess(upstream, runtime_state_dir=tmp_path / "runtime-state")

    try:
        result = client.call_tool("notebook.list_notebooks", {}, timeout_seconds=1)
    finally:
        client.stop()

    assert result == {"meta": {"authToken": "request-token"}}


def test_stdio_upstream_injects_configured_session_environment(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "session_env_worker.py",
        """
import json
import os
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": {
            "client_cwd": os.environ["MCP_BROKER_CLIENT_CWD"],
            "project_dir": os.environ["PROJECT_DIR"],
        },
    }), flush=True)
""",
    )
    upstream = UpstreamConfig(
        name="session-tool",
        command=sys.executable,
        args=[str(script)],
        session_env={"PROJECT_DIR": "client_cwd"},
    )
    client = StdioUpstreamProcess(
        upstream,
        runtime_state_dir=tmp_path / "runtime-state",
        session_context={"client_cwd": str(tmp_path / "client-project")},
    )

    try:
        result = client.call_tool("session.echo", {}, timeout_seconds=1)
    finally:
        client.stop()

    assert result == {
        "client_cwd": str(tmp_path / "client-project"),
        "project_dir": str(tmp_path / "client-project"),
    }


def test_stdio_upstream_lists_tools(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "tools_worker.py",
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "initialize":
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": request["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.0.1"},
            },
        }), flush=True)
        continue
    if request["method"] == "notifications/initialized":
        continue
    assert request["method"] == "tools/list"
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": {
            "tools": [
                {"name": "echo", "description": "Echo input"}
            ]
        },
    }), flush=True)
""",
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        assert client.list_tools(timeout_seconds=1) == [
            {"name": "echo", "description": "Echo input"}
        ]
    finally:
        client.stop()


def test_stdio_upstream_logs_tools_list_timeout_event(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "slow_tools_worker.py",
        """
import json
import sys
import time

for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "initialize":
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": request["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.0.1"},
            },
        }), flush=True)
        continue
    if request["method"] == "notifications/initialized":
        continue
    time.sleep(2)
""",
    )
    events: list[dict[str, object]] = []
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
        event_logger=lambda event, upstream, fields: events.append(
            {"event": event, "upstream": upstream} | fields
        ),
    )

    try:
        with pytest.raises(StdioUpstreamTimeout, match="upstream timed out: fake"):
            client.list_tools(timeout_seconds=1)
    finally:
        client.stop()

    assert {
        "event": "upstream.timeout",
        "upstream": "fake",
        "method": "tools/list",
        "timeout_seconds": 1,
    } in events
    assert client.health_snapshot()["last_error"] == "upstream timed out: fake"


def test_stdio_upstream_restarts_after_timeout_before_next_request(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "late_response_worker.py",
        """
import json
import os
from pathlib import Path
import sys
import time

marker = Path(os.environ["MCP_BROKER_UPSTREAM_STATE_DIR"]) / "timed-out-once"

for line in sys.stdin:
    request = json.loads(line)
    if not marker.exists():
        marker.write_text("yes", encoding="utf-8")
        time.sleep(1.25)
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": {
            "content": [{"type": "text", "text": request["params"]["arguments"]["value"]}],
        },
    }), flush=True)
""",
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        with pytest.raises(StdioUpstreamTimeout, match="upstream timed out: fake"):
            client.call_tool("fake.echo", {"value": "first"}, timeout_seconds=1)

        result = client.call_tool("fake.echo", {"value": "second"}, timeout_seconds=1)
    finally:
        client.stop()

    assert result == {"content": [{"type": "text", "text": "second"}]}
    assert client.health_snapshot()["restarts"] == 1


def test_stdio_upstream_initializes_before_first_tools_list_request(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "strict_initialization_worker.py",
        """
import json
import sys

initialized = False
poisoned = False

for line in sys.stdin:
    request = json.loads(line)
    if not initialized and request["method"] != "initialize":
        poisoned = True
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "error": {
                "code": -32600,
                "message": "Received request before initialization was complete",
            },
        }), flush=True)
        continue
    if request["method"] == "initialize":
        initialized = True
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": request["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.0.1"},
            },
        }), flush=True)
    elif request["method"] == "notifications/initialized":
        continue
    elif poisoned:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {
                "code": -32600,
                "message": "Received request before initialization was complete",
            },
        }), flush=True)
    else:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"first_method_after_init": request["method"], "tools": [{"name": "strict"}]},
        }), flush=True)
""",
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        assert client.list_tools(timeout_seconds=1) == [{"name": "strict"}]
    finally:
        client.stop()


def test_stdio_upstream_ignores_notifications_while_waiting_for_response(
    tmp_path: Path,
) -> None:
    script = _script(
        tmp_path,
        "notification_worker.py",
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "initialize":
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": request["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.0.1"},
            },
        }), flush=True)
    elif request["method"] == "notifications/initialized":
        print(json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {"level": "info", "data": "ready"},
        }), flush=True)
    elif request["method"] == "tools/list":
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"tools": [{"name": "search_graph"}]},
        }), flush=True)
""",
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        assert client.list_tools(timeout_seconds=1) == [{"name": "search_graph"}]
    finally:
        client.stop()


def test_stdio_upstream_initializes_when_required_before_listing_tools(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "initializing_tools_worker.py",
        """
import json
import sys

initialized = False

for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "initialize":
        initialized = True
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": request["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.0.1"},
            },
        }), flush=True)
    elif request["method"] == "notifications/initialized":
        continue
    elif not initialized:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": -32002, "message": "Server not initialized"},
        }), flush=True)
    else:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"tools": [{"name": "echo"}]},
        }), flush=True)
""",
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        assert client.list_tools(timeout_seconds=1) == [{"name": "echo"}]
    finally:
        client.stop()


def test_stdio_upstream_initializes_when_server_reports_initialization_incomplete(
    tmp_path: Path,
) -> None:
    script = _script(
        tmp_path,
        "initialization_incomplete_tools_worker.py",
        """
import json
import sys

initialized = False

for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "initialize":
        initialized = True
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": request["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.0.1"},
            },
        }), flush=True)
    elif request["method"] == "notifications/initialized":
        continue
    elif not initialized:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {
                "code": -32600,
                "message": "Received request before initialization was complete",
            },
        }), flush=True)
    else:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {"tools": [{"name": "kb_health"}]},
        }), flush=True)
""",
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        assert client.list_tools(timeout_seconds=1) == [{"name": "kb_health"}]
    finally:
        client.stop()


def test_stdio_upstream_retries_tool_call_after_initialization_error(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "initializing_call_worker.py",
        """
import json
import sys

initialized = False

for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "initialize":
        initialized = True
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": request["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.0.1"},
            },
        }), flush=True)
    elif request["method"] == "notifications/initialized":
        continue
    elif not initialized:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": -32002, "message": "Server not initialized"},
        }), flush=True)
    else:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "content": [{"type": "text", "text": request["params"]["name"]}],
            },
        }), flush=True)
""",
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        assert client.call_tool("fake.echo", {}, timeout_seconds=1) == {
            "content": [{"type": "text", "text": "fake.echo"}],
        }
    finally:
        client.stop()


def test_stdio_upstream_retries_tool_call_after_invalid_params_initialization_error(
    tmp_path: Path,
) -> None:
    script = _script(
        tmp_path,
        "invalid_params_before_init_worker.py",
        """
import json
import sys

initialized = False

for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "initialize":
        initialized = True
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": request["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.0.1"},
            },
        }), flush=True)
    elif request["method"] == "notifications/initialized":
        continue
    elif not initialized:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "error": {"code": -32602, "message": "Invalid request parameters", "data": ""},
        }), flush=True)
    else:
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "content": [{"type": "text", "text": request["params"]["name"]}],
            },
        }), flush=True)
""",
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        assert client.call_tool("fake.health", {}, timeout_seconds=1) == {
            "content": [{"type": "text", "text": "fake.health"}],
        }
    finally:
        client.stop()


def test_response_is_not_initialized_rejects_non_initialization_errors() -> None:
    from mcp_broker import upstream_stdio

    assert upstream_stdio._format_response_error({}) == "{}"
    assert upstream_stdio._response_is_not_initialized({"result": {}}) is False
    assert upstream_stdio._response_is_not_initialized({"error": {"message": 123}}) is False
    assert upstream_stdio._response_identity({"id": 0, "method": "roots/list"}) == (
        "id=0, method='roots/list'"
    )
    assert (
        upstream_stdio._response_is_not_initialized(
            {"error": {"code": -32600, "message": "different failure"}}
        )
        is False
    )
    assert (
        upstream_stdio._response_is_not_initialized(
            {"error": {"code": -32602, "message": "Invalid request parameters", "data": ""}}
        )
        is True
    )


def test_stdio_upstream_rejects_bad_tools_list_response(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "bad_tools_worker.py",
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if request["method"] == "initialize":
        print(json.dumps({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": request["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0.0.1"},
            },
        }), flush=True)
        continue
    if request["method"] == "notifications/initialized":
        continue
    print(json.dumps({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": {"tools": "bad"}
    }), flush=True)
""",
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        with pytest.raises(
            StdioUpstreamError,
            match="upstream tools/list response invalid: fake",
        ):
            client.list_tools(timeout_seconds=1)
        assert (
            client.health_snapshot()["last_error"]
            == "upstream tools/list response invalid: fake"
        )
    finally:
        client.stop()


def test_stdio_upstream_reports_health_snapshot(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "health_worker.py",
        """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {}}), flush=True)
""",
    )
    upstream = UpstreamConfig(name="fake", command=sys.executable, args=[str(script)])
    client = StdioUpstreamProcess(upstream, runtime_state_dir=tmp_path / "state")

    assert client.health_snapshot() == {
        "state": "configured",
        "pid": None,
        "cpu_percent": None,
        "memory_mb": None,
        "restarts": 0,
        "last_error": None,
    }

    try:
        client.call_tool("fake.echo", {}, timeout_seconds=1)
        snapshot = client.health_snapshot()

        assert client.status == "running"
        assert snapshot["state"] == "running"
        assert isinstance(snapshot["pid"], int)
        assert isinstance(snapshot["cpu_percent"], float)
        assert snapshot["memory_mb"] is None or isinstance(snapshot["memory_mb"], float)
        assert snapshot["restarts"] == 0
        assert snapshot["last_error"] is None
    finally:
        client.stop()


def test_stdio_upstream_reports_exited_status_and_restarts(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "one_shot_worker.py",
        """
import json
import sys

request = json.loads(sys.stdin.readline())
print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": {}}), flush=True)
""",
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        client.call_tool("fake.echo", {}, timeout_seconds=1)
        process = cast(subprocess.Popen[bytes], client._process)
        process.wait(timeout=1)

        assert client.status == "exited"

        client.call_tool("fake.echo", {}, timeout_seconds=1)

        assert client.health_snapshot()["restarts"] == 1
    finally:
        client.stop()


def test_stdio_upstream_ensure_running_restarts_exited_process(tmp_path: Path) -> None:
    script = _script(
        tmp_path,
        "long_running_worker.py",
        """
import time

time.sleep(30)
""",
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        client.ensure_running()
        first_process = cast(subprocess.Popen[bytes], client._process)
        first_process.terminate()
        first_process.wait(timeout=2)

        client.ensure_running()

        assert client.health_snapshot()["state"] == "running"
        assert client.health_snapshot()["restarts"] == 1
    finally:
        client.stop()


def test_stdio_upstream_ensure_running_maps_unexpected_restart_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import upstream_stdio

    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable),
        runtime_state_dir=tmp_path / "state",
    )
    monkeypatch.setattr(
        upstream_stdio.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("spawn bug")),
    )

    with pytest.raises(StdioUpstreamError, match="upstream failed to restart: fake: spawn bug"):
        client.ensure_running()

    assert client.health_snapshot()["last_error"] == "spawn bug"


def test_stdio_upstream_ensure_running_records_start_failure(tmp_path: Path) -> None:
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=str(tmp_path / "missing-command")),
        runtime_state_dir=tmp_path / "state",
    )

    with pytest.raises(StdioUpstreamError, match="upstream failed to start: fake"):
        client.ensure_running()

    assert "upstream failed to start: fake" in str(client.health_snapshot()["last_error"])


def test_stdio_upstream_maps_start_failure(tmp_path: Path) -> None:
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=str(tmp_path / "missing-command")),
        runtime_state_dir=tmp_path / "state",
    )

    with pytest.raises(StdioUpstreamError, match="upstream failed to start: fake"):
        client.call_tool("fake.echo", {}, timeout_seconds=1)

    assert "upstream failed to start: fake" in str(client.health_snapshot()["last_error"])


@pytest.mark.error_simulation
def test_stdio_upstream_health_handles_stale_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import upstream_stdio

    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable),
        runtime_state_dir=tmp_path / "state",
    )
    client._process = cast(Any, RunningProcessForHealth())
    monkeypatch.setattr(
        upstream_stdio.os,
        "getpgid",
        lambda _pid: (_ for _ in ()).throw(ProcessLookupError),
    )

    assert client.health_snapshot() == {
        "state": "exited",
        "pid": None,
        "cpu_percent": None,
        "memory_mb": None,
        "restarts": 0,
        "last_error": None,
    }


@pytest.mark.parametrize(
    ("body", "error_type", "message"),
    [
        (
            """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({"jsonrpc": "2.0", "id": "wrong", "result": {}}), flush=True)
""",
            StdioUpstreamError,
            "upstream response id mismatch: fake: expected 0, received id='wrong'",
        ),
        (
            """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"]}), flush=True)
""",
            StdioUpstreamError,
            "upstream response missing result: fake",
        ),
        (
            """
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    print(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "error": {
                    "code": -32000,
                    "message": "Auth token missing",
                    "data": {"hint": "run login"},
                },
            }
        ),
        flush=True,
    )
""",
            StdioUpstreamError,
            "upstream error from fake: -32000 Auth token missing data={'hint': 'run login'}",
        ),
        (
            """
import sys

for line in sys.stdin:
    print("[]", flush=True)
""",
            StdioUpstreamError,
            "upstream response must be an object: fake",
        ),
        (
            """
import sys

for line in sys.stdin:
    sys.exit(0)
""",
            StdioUpstreamError,
            "upstream exited without response: fake",
        ),
        (
            """
import time

time.sleep(2)
""",
            StdioUpstreamTimeout,
            "upstream timed out: fake",
        ),
    ],
)
def test_stdio_upstream_rejects_bad_responses(
    tmp_path: Path,
    body: str,
    error_type: type[Exception],
    message: str,
) -> None:
    script = _script(tmp_path, "bad_worker.py", body)
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable, args=[str(script)]),
        runtime_state_dir=tmp_path / "state",
    )

    try:
        timeout_seconds = 0 if error_type is StdioUpstreamTimeout else 1
        with pytest.raises(error_type, match=message):
            client.call_tool("fake.echo", {}, timeout_seconds=timeout_seconds)
        assert client.health_snapshot()["last_error"] == message
    finally:
        client.stop()


def test_stdio_upstream_rejects_closed_pipes(tmp_path: Path) -> None:
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable),
        runtime_state_dir=tmp_path / "state",
    )

    with pytest.raises(StdioUpstreamError, match="upstream stdin closed: fake"):
        client._write_request(cast(Any, ClosedPipeProcess(stdin=None, stdout=io.BytesIO())), {})

    with pytest.raises(StdioUpstreamError, match="upstream stdout closed: fake"):
        client._read_response(
            cast(Any, ClosedPipeProcess(stdin=io.BytesIO(), stdout=None)),
            timeout_seconds=0,
        )

    with pytest.raises(StdioUpstreamError, match="upstream stdin closed: fake"):
        client._write_request(cast(Any, ClosedPipeProcess(stdin=BrokenPipeStdin(), stdout=None)), {})


@pytest.mark.error_simulation
def test_stdio_upstream_stop_handles_missing_and_stubborn_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import upstream_stdio

    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable),
        runtime_state_dir=tmp_path / "state",
    )
    client.stop()
    process = StubbornProcess()
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(upstream_stdio.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    client._process = cast(Any, process)

    client.stop()

    assert process.waits == 2
    assert signals == [
        (process.pid, upstream_stdio.signal.SIGTERM),
        (process.pid, upstream_stdio.signal.SIGKILL),
        (process.pid, upstream_stdio.signal.SIGKILL),
    ]
    assert client._process is None


@pytest.mark.error_simulation
def test_stdio_upstream_stop_handles_process_group_signal_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import upstream_stdio

    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable),
        runtime_state_dir=tmp_path / "state",
    )
    process = StubbornProcess()
    attempts = 0

    def fail_signal(_pid: int, _sig: signal.Signals) -> None:
        nonlocal attempts
        attempts += 1
        raise PermissionError

    monkeypatch.setattr(upstream_stdio.os, "killpg", fail_signal)
    client._process = cast(Any, process)

    client.stop()

    assert attempts == 3
    assert process.waits == 2
    assert client._process is None


@pytest.mark.error_simulation
def test_stdio_upstream_stop_removes_metadata_by_name_when_path_not_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import upstream_stdio
    from mcp_broker.runtime_reaper import RuntimePaths, write_process_metadata

    paths = RuntimePaths.from_root(tmp_path / "runtime")
    metadata_path = write_process_metadata(
        paths,
        name="fake",
        pid=999_999,
        process_group_id=999_999,
        broker_pid=os.getpid(),
    )
    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable),
        runtime_state_dir=tmp_path / "state",
        runtime_paths=paths,
    )
    client._process = cast(Any, StubbornProcess())
    monkeypatch.setattr(upstream_stdio.os, "killpg", lambda _pid, _sig: None)
    monkeypatch.setattr(upstream_stdio, "_wait_for_process_group_stop", lambda _pgid: ())

    client.stop()

    assert not metadata_path.exists()
    assert client._process is None


@pytest.mark.error_simulation
def test_stdio_upstream_stop_handles_parent_that_survives_sigkill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import upstream_stdio

    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable),
        runtime_state_dir=tmp_path / "state",
    )
    process = NeverExitsProcess()
    monkeypatch.setattr(
        upstream_stdio.os,
        "getpgid",
        lambda _pid: (_ for _ in ()).throw(ProcessLookupError),
    )
    client._process = cast(Any, process)

    assert client.stop() == ()

    assert process.waits == 2
    assert client.health_snapshot()["last_error"] == "upstream did not exit after SIGKILL: fake"
    assert client._process is None


@pytest.mark.error_simulation
def test_stdio_process_group_wait_reports_remaining_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import upstream_stdio

    times = iter([0.0, 0.0, 1.0])
    monkeypatch.setattr(upstream_stdio.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(upstream_stdio, "_process_group_members", lambda _pgid: (111, 222))

    assert upstream_stdio._wait_for_process_group_stop(999) == (111, 222)


def test_stdio_process_group_members_parses_ps_output(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_broker import upstream_stdio

    class Completed:
        stdout = " 111\n\n 222\n"

    monkeypatch.setattr(upstream_stdio.subprocess, "run", lambda *_, **__: Completed())

    assert upstream_stdio._process_group_members(999) == (111, 222)


@pytest.mark.error_simulation
def test_stdio_start_restarts_without_stderr_drainer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import upstream_stdio

    client = StdioUpstreamProcess(
        UpstreamConfig(name="fake", command=sys.executable),
        runtime_state_dir=tmp_path / "state",
    )
    client._process = cast(Any, ExitedProcessWithPipes())
    client._stderr_drainer = None
    monkeypatch.setattr(
        upstream_stdio.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("spawn failed")),
    )

    with pytest.raises(StdioUpstreamError, match="upstream failed to start: fake: spawn failed"):
        client._start()

    assert client.health_snapshot()["restarts"] == 1


def test_stdio_close_process_pipes_skips_missing_stream_and_optional_stderr() -> None:
    from mcp_broker.upstream_stdio import _close_process_pipes

    process = ExitedProcessWithPipes(stdin=None)

    _close_process_pipes(cast(Any, process), include_stderr=False)

    assert process.stdout.closed is True
    assert process.stderr.closed is False


class ClosedPipeProcess:
    def __init__(self, *, stdin: object | None, stdout: object | None) -> None:
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = None


class BrokenPipeStdin:
    def write(self, _payload: bytes) -> int:
        raise BrokenPipeError

    def flush(self) -> None:
        raise AssertionError("flush should not run after a broken pipe")


class ExitedProcessWithPipes:
    def __init__(self, *, stdin: object | None = io.BytesIO()) -> None:
        self.pid = 999999
        self.stdin = stdin
        self.stdout = io.BytesIO()
        self.stderr = io.BytesIO()

    def poll(self) -> int:
        return 0


class RunningProcessForHealth:
    pid = 999998
    stdin = io.BytesIO()
    stdout = io.BytesIO()
    stderr = io.BytesIO()

    def poll(self) -> None:
        return None


class StubbornProcess:
    pid = 999999
    stdin = io.BytesIO()
    stdout = io.BytesIO()
    stderr = io.BytesIO()

    def __init__(self) -> None:
        self.waits = 0

    def poll(self) -> None:
        return None

    def wait(self, *, timeout: float) -> int:
        self.waits += 1
        if self.waits == 1:
            raise subprocess.TimeoutExpired("fake", timeout)
        return 0


class NeverExitsProcess:
    pid = 999997
    stdin = io.BytesIO()
    stdout = io.BytesIO()
    stderr = io.BytesIO()

    def __init__(self) -> None:
        self.waits = 0

    def poll(self) -> None:
        return None

    def wait(self, *, timeout: float) -> int:
        self.waits += 1
        raise subprocess.TimeoutExpired("fake", timeout)


def _script(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body.strip() + "\n", encoding="utf-8")
    return path
