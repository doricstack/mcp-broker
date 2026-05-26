from pathlib import Path

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


def test_tool_count_report_groups_namespaced_tools_by_upstream_prefix() -> None:
    from mcp_broker.tool_count import build_tool_count_report

    report = build_tool_count_report(
        profile="llm-profile",
        tools=[
            {"name": "read-store.search"},
            {"name": "remote-repo.create_issue"},
            {"name": "read-store.remember"},
        ],
    )

    assert report == {
        "profile": "llm-profile",
        "total_tools": 3,
        "upstream_counts": {
            "remote-repo": 1,
            "read-store": 2,
        },
        "tools": [
            "read-store.remember",
            "read-store.search",
            "remote-repo.create_issue",
        ],
    }


def test_tool_count_report_uses_first_namespace_segment_for_counts() -> None:
    from mcp_broker.tool_count import build_tool_count_report

    report = build_tool_count_report(
        profile="llm-profile",
        tools=[
            {"name": "broker.search_tools"},
            {"name": "project.file.search"},
            {"name": "project.file.read"},
            {"name": "standalone"},
        ],
    )

    assert report["upstream_counts"] == {
        "broker": 1,
        "project": 2,
        "standalone": 1,
    }


def test_tool_count_main_loads_config_and_reports_sorted_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import mcp_broker.tool_count as tool_count

    config_path = tmp_path / "broker.yaml"
    loaded_configs: list[Path] = []
    list_calls: list[dict[str, object]] = []

    class LoadedConfig:
        pass

    def from_file(path: Path) -> LoadedConfig:
        loaded_configs.append(path)
        return LoadedConfig()

    def list_profile_tools(**kwargs: object) -> dict[str, object]:
        list_calls.append(kwargs)
        return {
            "result": {
                "tools": [
                    {"name": "remote.write"},
                    {"name": "broker.search_tools"},
                ]
            }
        }

    monkeypatch.setattr(tool_count.BrokerConfig, "from_file", from_file)
    monkeypatch.setattr(tool_count, "_list_profile_tools", list_profile_tools)

    result = tool_count.main(["--config", str(config_path), "--profile", "review"])

    captured = capsys.readouterr()
    assert result == 0
    assert loaded_configs == [config_path]
    assert len(list_calls) == 1
    assert isinstance(list_calls[0]["config"], LoadedConfig)
    assert list_calls[0]["profile"] == "review"
    assert captured.err == ""
    assert captured.out == (
        '{"profile": "review", "tools": ["broker.search_tools", "remote.write"], '
        '"total_tools": 2, "upstream_counts": {"broker": 1, "remote": 1}}\n'
    )


def test_tool_count_main_reports_tools_list_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import yaml
    import mcp_broker.tool_count as tool_count

    config_path = tmp_path / "broker.yaml"
    config_path.write_text(yaml.safe_dump({"runtime": {"root": str(tmp_path / "runtime")}}), encoding="utf-8")
    monkeypatch.setattr(
        tool_count,
        "_list_profile_tools",
        lambda **_kwargs: {"error": {"message": "boom", "code": -32000}},
    )

    result = tool_count.main(["--config", str(config_path), "--profile", "llm"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err == '{"code": -32000, "message": "boom"}\n'


def test_tool_count_parse_args_requires_config_and_defaults_profile(capsys: pytest.CaptureFixture[str]) -> None:
    import mcp_broker.tool_count as tool_count

    args = tool_count._parse_args(["--config", "/tmp/broker.yaml"])

    assert args.config == "/tmp/broker.yaml"
    assert args.profile == "codex"
    with pytest.raises(SystemExit):
        tool_count._parse_args([])
    missing = capsys.readouterr()
    assert "--config" in missing.err


def test_tool_count_parse_args_help_names_command(capsys: pytest.CaptureFixture[str]) -> None:
    import mcp_broker.tool_count as tool_count

    with pytest.raises(SystemExit) as exc:
        tool_count._parse_args(["--help"])

    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert "\nCount broker-advertised MCP tools\n" in captured.out
    assert "--config" in captured.out
    assert "--profile" in captured.out


def test_tool_count_rethrows_unexpected_daemon_start_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import mcp_broker.tool_count as tool_count
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig

    class BrokenDaemon:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise tool_count.BrokerDaemonError("bind failed")

    config = BrokerConfig(
        runtime=RuntimeConfig.from_mapping({"root": str(tmp_path / "runtime")}),
        broker=BrokerSettings(),
        upstreams={},
    )
    monkeypatch.setattr(tool_count, "BrokerDaemon", BrokenDaemon)

    with pytest.raises(tool_count.BrokerDaemonError, match="bind failed"):
        tool_count._list_profile_tools(config=config, profile="llm")


def test_tool_count_starts_daemon_with_runtime_config_and_exact_requests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import mcp_broker.tool_count as tool_count
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig

    daemon_events: list[tuple[str, object]] = []

    class RecordingDaemon:
        def __init__(self, **kwargs: object) -> None:
            daemon_events.append(("init", kwargs))

        def start(self) -> None:
            daemon_events.append(("start", None))

        def join(self, *, timeout: int) -> None:
            daemon_events.append(("join", timeout))

        def stop(self) -> None:
            daemon_events.append(("stop", None))

    requests: list[tuple[Path, dict[str, object]]] = []

    def request(socket_path: Path, payload: dict[str, object]) -> dict[str, object]:
        requests.append((socket_path, payload))
        if payload["method"] == "tools/list":
            return {"result": {"tools": [{"name": "broker.search_tools"}]}}
        return {"result": {}}

    runtime_root = tmp_path / "runtime"
    config = BrokerConfig(
        runtime=RuntimeConfig.from_mapping({"root": str(runtime_root)}),
        broker=BrokerSettings(),
        upstreams={},
    )
    monkeypatch.setattr(tool_count, "BrokerDaemon", RecordingDaemon)
    monkeypatch.setattr(tool_count, "_request", request)

    response = tool_count._list_profile_tools(config=config, profile="llm")

    assert response == {"result": {"tools": [{"name": "broker.search_tools"}]}}
    assert daemon_events == [
        (
            "init",
            {
                "runtime_root": config.runtime.root,
                "socket_path": config.runtime.socket_path,
                "broker_config": config,
            },
        ),
        ("start", None),
        ("join", 5),
        ("stop", None),
    ]
    assert requests == [
        (
            config.runtime.socket_path,
            {
                "jsonrpc": "2.0",
                "id": "initialize",
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
        ),
        (
            config.runtime.socket_path,
            {
                "jsonrpc": "2.0",
                "id": "tools-count",
                "method": "tools/list",
                "params": {"profile": "llm"},
            },
        ),
        (
            config.runtime.socket_path,
            {"jsonrpc": "2.0", "id": "stop", "method": "broker/stop"},
        ),
    ]


def test_tool_count_reuses_existing_daemon_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    import mcp_broker.tool_count as tool_count
    from mcp_broker.config import BrokerConfig, BrokerSettings, RuntimeConfig

    class AlreadyRunningDaemon:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise tool_count.BrokerDaemonError("broker daemon already running")

        def stop(self) -> None:
            raise AssertionError("existing daemon must not be stopped by tools-count")

    requests: list[dict[str, object]] = []

    def request(_socket_path: Path, payload: dict[str, object]) -> dict[str, object]:
        requests.append(payload)
        return {"result": {"tools": [{"name": "broker.search_tools"}]}}

    config = BrokerConfig(
        runtime=RuntimeConfig.from_mapping({"root": str(tmp_path / "runtime")}),
        broker=BrokerSettings(),
        upstreams={},
    )
    monkeypatch.setattr(tool_count, "BrokerDaemon", AlreadyRunningDaemon)
    monkeypatch.setattr(tool_count, "_request", request)

    response = tool_count._list_profile_tools(config=config, profile="llm")

    assert response == {"result": {"tools": [{"name": "broker.search_tools"}]}}
    assert [request["id"] for request in requests] == ["initialize", "tools-count"]


def test_tool_count_request_uses_unix_stream_socket_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket
    import mcp_broker.tool_count as tool_count

    events: list[tuple[str, object]] = []

    class RecordingSocket:
        def __init__(self) -> None:
            self.chunks = [b'{"result": {"tools": []}}\n', b""]

        def __enter__(self) -> "RecordingSocket":
            events.append(("enter", None))
            return self

        def __exit__(self, *_exc: object) -> None:
            events.append(("exit", None))

        def settimeout(self, timeout: int) -> None:
            events.append(("timeout", timeout))

        def connect(self, socket_path: str) -> None:
            events.append(("connect", socket_path))

        def sendall(self, payload: bytes) -> None:
            events.append(("sendall", payload))

        def recv(self, size: int) -> bytes:
            events.append(("recv", size))
            return self.chunks.pop(0)

    def socket_factory(family: int, sock_type: int) -> RecordingSocket:
        events.append(("socket", (family, sock_type)))
        return RecordingSocket()

    monkeypatch.setattr(tool_count.socket, "socket", socket_factory)

    response = tool_count._request(Path("/tmp/broker.sock"), {"id": "one"})

    assert response == {"result": {"tools": []}}
    assert events == [
        ("socket", (socket.AF_UNIX, socket.SOCK_STREAM)),
        ("enter", None),
        ("timeout", 30),
        ("connect", "/tmp/broker.sock"),
        ("sendall", b'{"id": "one"}\n'),
        ("recv", 65536),
        ("exit", None),
    ]


def test_tool_count_request_accumulates_multiple_socket_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.tool_count as tool_count

    class ChunkedSocket:
        def __init__(self) -> None:
            self.chunks = [b'{"result": ', b'{"tools": ', b"[]}}\n"]

        def __enter__(self) -> "ChunkedSocket":
            return self

        def __exit__(self, *_exc: object) -> None:
            pass

        def settimeout(self, _timeout: int) -> None:
            pass

        def connect(self, _socket_path: str) -> None:
            pass

        def sendall(self, _payload: bytes) -> None:
            pass

        def recv(self, _size: int) -> bytes:
            return self.chunks.pop(0)

    monkeypatch.setattr(tool_count.socket, "socket", lambda *_args: ChunkedSocket())

    response = tool_count._request(Path("/tmp/broker.sock"), {"id": "one"})

    assert response == {"result": {"tools": []}}


def test_tool_count_request_rejects_socket_close_before_newline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import mcp_broker.tool_count as tool_count

    class ClosedBeforeFrameSocket:
        def __init__(self) -> None:
            self.chunks = [b'{"result": {"tools": []}}', b""]

        def __enter__(self) -> "ClosedBeforeFrameSocket":
            return self

        def __exit__(self, *_exc: object) -> None:
            pass

        def settimeout(self, _timeout: int) -> None:
            pass

        def connect(self, _socket_path: str) -> None:
            pass

        def sendall(self, _payload: bytes) -> None:
            pass

        def recv(self, _size: int) -> bytes:
            return self.chunks.pop(0)

    monkeypatch.setattr(tool_count.socket, "socket", lambda *_args: ClosedBeforeFrameSocket())

    with pytest.raises(ValueError) as exc:
        tool_count._request(Path("/tmp/broker.sock"), {"id": "one"})
    assert str(exc.value) == "broker response closed before newline frame"


def test_tool_count_request_stops_reading_when_socket_closes(tmp_path) -> None:
    import socket
    import tempfile
    import threading
    import mcp_broker.tool_count as tool_count

    del tmp_path
    temp_dir = tempfile.TemporaryDirectory(prefix="mb-tool-count-", dir="/tmp")
    socket_path = temp_dir.name + "/tool-count.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(1)

    def serve_once() -> None:
        connection, _ = server.accept()
        with connection:
            connection.recv(65536)
        server.close()

    thread = threading.Thread(target=serve_once)
    thread.start()
    try:
        with pytest.raises(ValueError) as exc:
            tool_count._request(Path(socket_path), {"id": "one"})
        assert str(exc.value) == "broker response closed before newline frame"
    finally:
        thread.join(timeout=2)
        server.close()
        temp_dir.cleanup()


def test_tool_count_request_reads_chunked_json_response(tmp_path) -> None:
    import json
    import socket
    import tempfile
    import threading
    import mcp_broker.tool_count as tool_count

    del tmp_path
    temp_dir = tempfile.TemporaryDirectory(prefix="mb-tool-count-", dir="/tmp")
    socket_path = temp_dir.name + "/tool-count.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    server.listen(1)
    received: list[bytes] = []

    def serve_once() -> None:
        connection, _ = server.accept()
        with connection:
            received.append(connection.recv(65536))
            connection.sendall(b'{"result": ')
            connection.sendall(b'{"tools": []}}\n')
        server.close()

    thread = threading.Thread(target=serve_once)
    thread.start()
    try:
        response = tool_count._request(Path(socket_path), {"id": "one"})
    finally:
        thread.join(timeout=2)
        server.close()
        temp_dir.cleanup()

    assert response == {"result": {"tools": []}}
    assert received == [json.dumps({"id": "one"}).encode("utf-8") + b"\n"]
