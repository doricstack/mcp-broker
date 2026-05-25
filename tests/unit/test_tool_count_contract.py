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
        lambda **_kwargs: {"error": {"code": -32000, "message": "boom"}},
    )

    result = tool_count.main(["--config", str(config_path), "--profile", "llm"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err == '{"code": -32000, "message": "boom"}\n'


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
        with pytest.raises(ValueError, match="Expecting value"):
            tool_count._request(Path(socket_path), {"id": "one"})
    finally:
        thread.join(timeout=2)
        server.close()
        temp_dir.cleanup()
