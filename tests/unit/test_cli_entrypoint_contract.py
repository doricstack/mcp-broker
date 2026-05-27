import runpy
import os
import sys
from io import BytesIO
from pathlib import Path

import pytest


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


@pytest.mark.parametrize(
    "module_name",
    [
        "mcp_broker.client",
        "mcp_broker.cli",
        "mcp_broker.config_render",
        "mcp_broker.config_validate",
        "mcp_broker.daemon",
        "mcp_broker.deferred_acceptance",
        "mcp_broker.discovery_parity",
        "mcp_broker.doctor",
        "mcp_broker.facade_smoke",
        "mcp_broker.profile_validation",
        "mcp_broker.profile_snippet",
        "mcp_broker.project_mcp",
        "mcp_broker.runtime_reaper",
        "mcp_broker.tool_count",
    ],
)
def test_cli_module_entrypoints_delegate_to_argparse_help(
    module_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", [module_name, "--help"])
    previous_module = sys.modules.pop(module_name, None)

    try:
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module(module_name, run_name="__main__")
    finally:
        if previous_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous_module

    assert exc_info.value.code == 0


def test_top_level_cli_init_copies_packaged_example(tmp_path: Path) -> None:
    from mcp_broker.cli import main

    config_path = tmp_path / "configs" / "broker.yaml"

    assert main(["init", "--config", str(config_path)]) == 0

    rendered = config_path.read_text(encoding="utf-8")
    assert "runtime:" in rendered
    assert "upstreams:" in rendered
    assert "/Users/" not in rendered


def test_top_level_cli_init_does_not_overwrite_existing_config(tmp_path: Path) -> None:
    from mcp_broker.cli import main

    config_path = tmp_path / "broker.yaml"
    config_path.write_text("existing: true\n", encoding="utf-8")

    assert main(["init", "--config", str(config_path)]) == 0

    assert config_path.read_text(encoding="utf-8") == "existing: true\n"


def test_top_level_cli_render_dry_run_uses_config_contract(tmp_path: Path) -> None:
    from mcp_broker.cli import main

    runtime_root = tmp_path / "runtime"
    client_config = tmp_path / "client.toml"
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        f"""
runtime:
  root: {runtime_root}
clients:
  generic-client:
    format: codex-toml
    config_path: {client_config}
    entry_name: mcp-broker
    command: mcp-broker-client
upstreams: {{}}
""".strip(),
        encoding="utf-8",
    )

    assert main(["render", "generic-client", "--config", str(config_path), "--dry-run"]) == 0

    rendered_path = runtime_root / "renders" / "generic-client.config.toml"
    assert rendered_path.exists()
    assert not client_config.exists()
    assert '[mcp_servers."mcp-broker"]' in rendered_path.read_text(encoding="utf-8")


def test_top_level_cli_builds_daemon_argv_from_public_options(tmp_path: Path) -> None:
    from mcp_broker.cli import daemon_argv, stdio_argv

    runtime_root = tmp_path / "runtime"
    socket_path = runtime_root / "sockets" / "broker.sock"
    config_path = tmp_path / "broker.yaml"

    assert daemon_argv(
        command="start",
        runtime_root=runtime_root,
        socket_path=socket_path,
        config_path=config_path,
    ) == [
        "serve",
        "--runtime-root",
        str(runtime_root),
        "--socket-path",
        str(socket_path),
        "--config",
        str(config_path),
    ]
    assert daemon_argv(
        command="status",
        runtime_root=runtime_root,
        socket_path=socket_path,
        config_path=None,
    ) == [
        "status",
        "--runtime-root",
        str(runtime_root),
        "--socket-path",
        str(socket_path),
    ]
    assert stdio_argv(
        runtime_root=runtime_root,
        socket_path=socket_path,
        config_path=config_path,
        profile="generic-client",
        init_if_missing=False,
    ) == [
        "--runtime-root",
        str(runtime_root),
        "--socket-path",
        str(socket_path),
        "--config",
        str(config_path),
        "--profile",
        "generic-client",
    ]


def test_top_level_cli_parser_requires_command() -> None:
    from mcp_broker.cli import build_parser

    parser = build_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([])

    assert exc_info.value.code == 2


def test_top_level_cli_parser_preserves_handlers_and_path_types(
    tmp_path: Path,
) -> None:
    from mcp_broker import cli

    parser = cli.build_parser()
    config_path = tmp_path / "broker.yaml"
    runtime_root = tmp_path / "runtime"
    socket_path = tmp_path / "broker.sock"

    parsed_init = parser.parse_args(["init", "--config", str(config_path)])
    parsed_start = parser.parse_args(
        [
            "start",
            "--runtime-root",
            str(runtime_root),
            "--socket-path",
            str(socket_path),
            "--config",
            str(config_path),
        ]
    )
    parsed_render = parser.parse_args(["render", "generic-client", "--config", str(config_path)])

    assert parsed_init.command == "init"
    assert parsed_init.handler is cli.handle_init
    assert parsed_init.config == config_path
    assert parsed_start.command == "start"
    assert parsed_start.handler is cli.handle_daemon
    assert parsed_start.runtime_root == runtime_root
    assert parsed_start.socket_path == socket_path
    assert parsed_start.config == config_path
    assert parsed_render.command == "render"
    assert parsed_render.handler is cli.handle_render
    assert parsed_render.client == "generic-client"
    assert parsed_render.config == config_path


def test_top_level_cli_parser_help_text_is_stable() -> None:
    from mcp_broker.cli import build_parser

    parser = build_parser()
    help_text = parser.format_help()

    assert parser.description == "Initialize, run, and inspect mcp-broker"
    assert "init" in help_text
    assert "Create a private config from the public example" in help_text
    assert "start" in help_text
    assert "Start the broker daemon in the foreground" in help_text
    assert "stdio" in help_text
    assert "Run the broker daemon and stdio client in one process" in help_text
    assert "status" in help_text
    assert "Query broker daemon status" in help_text
    assert "stop" in help_text
    assert "Ask the broker daemon to stop" in help_text
    assert "render" in help_text
    assert "Render one client config" in help_text
    assert "XX" not in help_text
    assert "INITIALIZE, RUN, AND INSPECT MCP-BROKER" not in help_text


def test_top_level_cli_parser_defaults_use_configured_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    runtime_root = tmp_path / "runtime"
    socket_path = tmp_path / "broker.sock"
    config_path = tmp_path / "broker.yaml"
    monkeypatch.setenv("MCP_BROKER_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("MCP_BROKER_SOCKET", str(socket_path))
    monkeypatch.setenv("MCP_BROKER_CONFIG", str(config_path))

    parser = cli.build_parser()
    parsed_init = parser.parse_args(["init"])
    parsed_start = parser.parse_args(["start"])
    parsed_stdio = parser.parse_args(["stdio"])
    parsed_status = parser.parse_args(["status"])
    parsed_stop = parser.parse_args(["stop"])
    parsed_render = parser.parse_args(["render", "generic-client"])

    assert parsed_init.config == config_path
    assert parsed_init.template is None
    assert parsed_init.force is False
    assert parsed_start.config == config_path
    assert parsed_start.runtime_root == runtime_root
    assert parsed_start.socket_path == socket_path
    assert parsed_stdio.config == config_path
    assert parsed_stdio.runtime_root == runtime_root
    assert parsed_stdio.socket_path == socket_path
    assert parsed_stdio.init_if_missing is False
    assert parsed_stdio.ready_attempts == 50
    assert isinstance(parsed_stdio.ready_attempts, int)
    assert parsed_status.runtime_root == runtime_root
    assert parsed_status.socket_path == socket_path
    assert parsed_stop.runtime_root == runtime_root
    assert parsed_stop.socket_path == socket_path
    assert parsed_render.config == config_path
    assert parsed_render.dry_run is True


def test_top_level_cli_stdio_parser_uses_environment_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.cli import build_parser

    monkeypatch.setenv("MCP_BROKER_PROFILE", "env-profile")
    monkeypatch.setenv("MCP_BROKER_READY_ATTEMPTS", "7")
    parser = build_parser()

    parsed = parser.parse_args(
        [
            "stdio",
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--socket-path",
            str(tmp_path / "broker.sock"),
            "--config",
            str(tmp_path / "broker.yaml"),
        ]
    )

    assert parsed.profile == "env-profile"
    assert parsed.ready_attempts == 7
    assert isinstance(parsed.ready_attempts, int)


def test_top_level_cli_stdio_parser_parses_ready_attempts_as_int(
    tmp_path: Path,
) -> None:
    from mcp_broker.cli import build_parser

    parser = build_parser()

    parsed = parser.parse_args(
        [
            "stdio",
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--socket-path",
            str(tmp_path / "broker.sock"),
            "--config",
            str(tmp_path / "broker.yaml"),
            "--ready-attempts",
            "8",
        ]
    )

    assert parsed.ready_attempts == 8
    assert isinstance(parsed.ready_attempts, int)


def test_top_level_cli_stdio_delegates_runtime_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    calls: list[list[str]] = []

    def stdio_runner(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    config_path = tmp_path / "broker.yaml"
    runtime_root = tmp_path / "runtime"
    socket_path = runtime_root / "broker.sock"
    monkeypatch.setattr(cli, "stdio_main", stdio_runner)

    assert (
        cli.main(
            [
                "stdio",
                "--runtime-root",
                str(runtime_root),
                "--socket-path",
                str(socket_path),
                "--config",
                str(config_path),
                "--profile",
                "generic-client",
            ]
        )
        == 0
    )

    assert calls == [
        [
            "--runtime-root",
            str(runtime_root),
            "--socket-path",
            str(socket_path),
            "--config",
            str(config_path),
            "--profile",
            "generic-client",
            "--ready-attempts",
            "50",
        ]
    ]


def test_top_level_cli_stdio_delegates_environment_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    calls: list[list[str]] = []

    def stdio_runner(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr(cli, "stdio_main", stdio_runner)
    monkeypatch.setenv("MCP_BROKER_PROFILE", "env-profile")
    monkeypatch.setenv("MCP_BROKER_READY_ATTEMPTS", "3")

    assert (
        cli.main(
            [
                "stdio",
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(tmp_path / "broker.sock"),
                "--config",
                str(tmp_path / "broker.yaml"),
            ]
        )
        == 0
    )

    assert calls == [
        [
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--socket-path",
            str(tmp_path / "broker.sock"),
            "--config",
            str(tmp_path / "broker.yaml"),
            "--profile",
            "env-profile",
            "--ready-attempts",
            "3",
        ]
    ]


def test_top_level_cli_stdio_delegates_init_if_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    calls: list[list[str]] = []

    def stdio_runner(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr(cli, "stdio_main", stdio_runner)

    assert (
        cli.main(
            [
                "stdio",
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(tmp_path / "broker.sock"),
                "--config",
                str(tmp_path / "broker.yaml"),
                "--init-if-missing",
            ]
        )
        == 0
    )

    assert calls == [
        [
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--socket-path",
            str(tmp_path / "broker.sock"),
            "--config",
            str(tmp_path / "broker.yaml"),
            "--init-if-missing",
            "--ready-attempts",
            "50",
        ]
    ]


def test_top_level_cli_builds_stdio_argv_without_optional_profile(tmp_path: Path) -> None:
    from mcp_broker.cli import stdio_argv

    runtime_root = tmp_path / "runtime"
    socket_path = runtime_root / "broker.sock"
    config_path = tmp_path / "broker.yaml"

    assert stdio_argv(
        runtime_root=runtime_root,
        socket_path=socket_path,
        config_path=config_path,
        profile=None,
        init_if_missing=True,
    ) == [
        "--runtime-root",
        str(runtime_root),
        "--socket-path",
        str(socket_path),
        "--config",
        str(config_path),
        "--init-if-missing",
    ]


def test_top_level_cli_stdio_argv_default_does_not_enable_init(tmp_path: Path) -> None:
    import inspect

    from mcp_broker.cli import stdio_argv

    runtime_root = tmp_path / "runtime"
    socket_path = runtime_root / "broker.sock"
    config_path = tmp_path / "broker.yaml"

    assert inspect.signature(stdio_argv).parameters["init_if_missing"].default is inspect.Parameter.empty
    assert stdio_argv(
        runtime_root=runtime_root,
        socket_path=socket_path,
        config_path=config_path,
        profile=None,
        init_if_missing=False,
    ) == [
        "--runtime-root",
        str(runtime_root),
        "--socket-path",
        str(socket_path),
        "--config",
        str(config_path),
    ]


def test_top_level_cli_stdio_runs_daemon_and_client_in_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    config_path = _stdio_config(tmp_path)
    monkeypatch.setattr(sys, "stdin", _BinaryConsole(b""))
    monkeypatch.setattr(sys, "stdout", _BinaryConsole())

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(_stdio_socket(tmp_path)),
                "--config",
                str(config_path),
                "--profile",
                "generic-client",
            ]
        )
        == 0
    )


def test_top_level_cli_stdio_requires_runtime_socket_and_config() -> None:
    from mcp_broker import cli

    missing_arg_cases = [
        ["--socket-path", "broker.sock", "--config", "broker.yaml"],
        ["--runtime-root", "runtime", "--config", "broker.yaml"],
        ["--runtime-root", "runtime", "--socket-path", "broker.sock"],
    ]

    for argv in missing_arg_cases:
        with pytest.raises(SystemExit) as exc_info:
            cli.stdio_main(argv)
        assert exc_info.value.code == 2


def test_top_level_cli_stdio_passes_config_socket_profile_and_buffers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    config_path = _stdio_config(tmp_path)
    socket_path = _stdio_socket(tmp_path)
    seen: dict[str, object] = {}

    class FakeDaemon:
        def __init__(self, *, runtime_root: Path, socket_path: Path, broker_config: object) -> None:
            seen["runtime_root"] = runtime_root
            seen["daemon_socket_path"] = socket_path
            seen["broker_config"] = broker_config

        def start(self) -> None:
            seen["started"] = True

        def stop(self) -> None:
            seen["stopped"] = True

    class FakeClientShim:
        def __init__(self, *, socket_path: Path, profile: str | None) -> None:
            seen["client_socket_path"] = socket_path
            seen["profile"] = profile

        def run_stdio(self, stdin: object, stdout: object) -> None:
            seen["stdin"] = stdin
            seen["stdout"] = stdout

    stdin = _BinaryConsole(b'{"jsonrpc":"2.0","id":"unit"}\n')
    stdout = _BinaryConsole()
    monkeypatch.setattr(cli, "BrokerDaemon", FakeDaemon)
    monkeypatch.setattr(cli, "ClientShim", FakeClientShim)
    monkeypatch.setattr(cli, "_wait_for_socket", lambda socket_path, attempts: True)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(socket_path),
                "--config",
                str(config_path),
                "--profile",
                "generic-client",
                "--ready-attempts",
                "3",
            ]
        )
        == 0
    )

    assert seen["runtime_root"] == tmp_path / "runtime"
    assert seen["daemon_socket_path"] == socket_path
    assert seen["client_socket_path"] == socket_path
    assert seen["profile"] == "generic-client"
    assert seen["stdin"] is stdin.buffer
    assert seen["stdout"] is stdout.buffer
    assert seen["started"] is True
    assert seen["stopped"] is True
    assert seen["broker_config"].profiles["generic-client"].max_tools == 200


def test_top_level_cli_stdio_uses_existing_daemon_when_init_if_missing_sees_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    config_path = _stdio_config(tmp_path)
    socket_path = _stdio_socket(tmp_path)
    seen: dict[str, object] = {}

    class FakeDaemon:
        def __init__(self, *, runtime_root: Path, socket_path: Path, broker_config: object) -> None:
            seen["runtime_root"] = runtime_root
            seen["daemon_socket_path"] = socket_path
            seen["broker_config"] = broker_config

        def start(self) -> None:
            raise cli.BrokerDaemonError("broker daemon already running: pid 123")

        def stop(self) -> None:
            raise AssertionError("stdio must not stop a daemon it did not start")

    class FakeClientShim:
        def __init__(self, *, socket_path: Path, profile: str | None) -> None:
            seen["client_socket_path"] = socket_path
            seen["profile"] = profile

        def run_stdio(self, stdin: object, stdout: object) -> None:
            seen["stdin"] = stdin
            seen["stdout"] = stdout

    stdin = _BinaryConsole(b"")
    stdout = _BinaryConsole()
    monkeypatch.setattr(cli, "BrokerDaemon", FakeDaemon)
    monkeypatch.setattr(cli, "ClientShim", FakeClientShim)
    monkeypatch.setattr(cli, "_wait_for_socket", lambda socket_path, attempts: True)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(socket_path),
                "--config",
                str(config_path),
                "--profile",
                "generic-client",
                "--init-if-missing",
            ]
        )
        == 0
    )

    assert seen["daemon_socket_path"] == socket_path
    assert seen["client_socket_path"] == socket_path
    assert seen["profile"] == "generic-client"
    assert seen["stdin"] is stdin.buffer
    assert seen["stdout"] is stdout.buffer


def test_top_level_cli_stdio_reports_unexpected_daemon_start_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker import cli

    config_path = _stdio_config(tmp_path)
    socket_path = _stdio_socket(tmp_path)

    class FakeDaemon:
        def __init__(self, *, runtime_root: Path, socket_path: Path, broker_config: object) -> None:
            self.stop_called = False

        def start(self) -> None:
            raise cli.BrokerDaemonError("runtime lock is corrupt")

        def stop(self) -> None:
            raise AssertionError("stdio must not stop a daemon that failed to start")

    class UnexpectedClientShim:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("client shim must not run when daemon start fails")

    monkeypatch.setattr(cli, "BrokerDaemon", FakeDaemon)
    monkeypatch.setattr(cli, "ClientShim", UnexpectedClientShim)
    monkeypatch.setattr(
        cli,
        "_wait_for_socket",
        lambda _socket_path, _attempts: (_ for _ in ()).throw(
            AssertionError("socket wait must not run when daemon start fails")
        ),
    )

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(socket_path),
                "--config",
                str(config_path),
                "--profile",
                "generic-client",
                "--init-if-missing",
            ]
        )
        == 1
    )

    assert capsys.readouterr().err == "runtime lock is corrupt\n"


def test_top_level_cli_stdio_init_error_stops_before_daemon(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    calls: list[tuple[object, ...]] = []

    def initialize_config(config_path: Path, *, template_path: Path, force: bool) -> int:
        calls.append((config_path, template_path, force))
        return 17

    class UnexpectedDaemon:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("daemon must not start when init fails")

    template_path = tmp_path / "template.yaml"
    config_path = tmp_path / "generated" / "broker.yaml"
    monkeypatch.setattr(cli, "initialize_config", initialize_config)
    monkeypatch.setattr(cli, "default_template_path", lambda: template_path)
    monkeypatch.setattr(cli, "BrokerDaemon", UnexpectedDaemon)

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(tmp_path / "broker.sock"),
                "--config",
                str(config_path),
                "--init-if-missing",
            ]
        )
        == 17
    )

    assert calls == [(config_path, template_path, False)]


def test_top_level_cli_stdio_initializes_missing_config_from_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    template_path = _stdio_config(tmp_path)
    config_path = tmp_path / "generated" / "broker.yaml"
    monkeypatch.setattr(cli, "default_template_path", lambda: template_path)
    monkeypatch.setattr(sys, "stdin", _BinaryConsole(b""))
    monkeypatch.setattr(sys, "stdout", _BinaryConsole())

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(_stdio_socket(tmp_path)),
                "--config",
                str(config_path),
                "--profile",
                "generic-client",
                "--init-if-missing",
            ]
        )
        == 0
    )

    assert config_path.exists()


def test_top_level_cli_stdio_reports_missing_config(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from mcp_broker import cli

    config_path = tmp_path / "missing.yaml"

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(_stdio_socket(tmp_path)),
                "--config",
                str(config_path),
            ]
        )
        == 1
    )

    assert f"missing config: {config_path}" in capsys.readouterr().err


def test_top_level_cli_stdio_returns_template_initialization_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker import cli

    missing_template = tmp_path / "missing-template.yaml"
    config_path = tmp_path / "generated" / "broker.yaml"
    monkeypatch.setattr(cli, "default_template_path", lambda: missing_template)

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(_stdio_socket(tmp_path)),
                "--config",
                str(config_path),
                "--init-if-missing",
            ]
        )
        == 1
    )

    assert f"missing config template: {missing_template}" in capsys.readouterr().err


def test_top_level_cli_stdio_init_success_must_leave_config_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    def initialize_config(config_path: Path, *, template_path: Path, force: bool) -> int:
        return 0

    class UnexpectedDaemon:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("daemon must not start without a config file")

    monkeypatch.setattr(cli, "initialize_config", initialize_config)
    monkeypatch.setattr(cli, "default_template_path", lambda: tmp_path / "template.yaml")
    monkeypatch.setattr(cli, "BrokerDaemon", UnexpectedDaemon)

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(tmp_path / "broker.sock"),
                "--config",
                str(tmp_path / "generated" / "broker.yaml"),
                "--init-if-missing",
            ]
        )
        == 1
    )


def test_top_level_cli_stdio_reports_socket_readiness_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker import cli

    config_path = _stdio_config(tmp_path)
    socket_path = _stdio_socket(tmp_path)
    monkeypatch.setattr(cli, "_wait_for_socket", lambda socket_path, attempts: False)

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(socket_path),
                "--config",
                str(config_path),
            ]
        )
        == 1
    )

    assert f"broker socket did not become ready: {socket_path}" in capsys.readouterr().err


def test_top_level_cli_stdio_reports_client_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker import cli
    from mcp_broker.client import ClientShimError

    config_path = _stdio_config(tmp_path)

    def fail_stdio(*args: object, **kwargs: object) -> None:
        raise ClientShimError("client failed")

    monkeypatch.setattr(cli.ClientShim, "run_stdio", fail_stdio)
    monkeypatch.setattr(sys, "stdin", _BinaryConsole(b""))
    monkeypatch.setattr(sys, "stdout", _BinaryConsole())

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(_stdio_socket(tmp_path)),
                "--config",
                str(config_path),
            ]
        )
        == 1
    )

    assert "client failed" in capsys.readouterr().err


def test_top_level_cli_stdio_help_text_is_stable(capsys: pytest.CaptureFixture[str]) -> None:
    from mcp_broker import cli

    with pytest.raises(SystemExit) as exc_info:
        cli.stdio_main(["--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "Run mcp-broker as a one-process stdio server" in help_text
    assert "--ready-attempts" in help_text
    assert "XX" not in help_text
    assert "RUN MCP-BROKER AS A ONE-PROCESS STDIO SERVER" not in help_text


def test_top_level_cli_stdio_passes_ready_attempts_to_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    config_path = _stdio_config(tmp_path)
    seen: dict[str, object] = {}

    class FakeDaemon:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    class FakeClientShim:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run_stdio(self, _stdin: object, _stdout: object) -> None:
            pass

    def wait_for_socket(socket_path: Path, *, attempts: int) -> bool:
        seen["attempts"] = attempts
        return True

    monkeypatch.setattr(cli, "BrokerDaemon", FakeDaemon)
    monkeypatch.setattr(cli, "ClientShim", FakeClientShim)
    monkeypatch.setattr(cli, "_wait_for_socket", wait_for_socket)
    monkeypatch.setattr(sys, "stdin", _BinaryConsole(b""))
    monkeypatch.setattr(sys, "stdout", _BinaryConsole())

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(_stdio_socket(tmp_path)),
                "--config",
                str(config_path),
                "--ready-attempts",
                "4",
            ]
        )
        == 0
    )

    assert seen["attempts"] == 4
    assert isinstance(seen["attempts"], int)


def test_top_level_cli_stdio_uses_default_ready_attempts_for_waiter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    config_path = _stdio_config(tmp_path)
    seen: dict[str, object] = {}

    class FakeDaemon:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            pass

        def stop(self) -> None:
            pass

    class FakeClientShim:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run_stdio(self, _stdin: object, _stdout: object) -> None:
            pass

    def wait_for_socket(socket_path: Path, *, attempts: int) -> bool:
        seen["attempts"] = attempts
        return True

    monkeypatch.setattr(cli, "BrokerDaemon", FakeDaemon)
    monkeypatch.setattr(cli, "ClientShim", FakeClientShim)
    monkeypatch.setattr(cli, "_wait_for_socket", wait_for_socket)
    monkeypatch.setattr(sys, "stdin", _BinaryConsole(b""))
    monkeypatch.setattr(sys, "stdout", _BinaryConsole())

    assert (
        cli.stdio_main(
            [
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(_stdio_socket(tmp_path)),
                "--config",
                str(config_path),
            ]
        )
        == 0
    )

    assert seen["attempts"] == 50


def test_top_level_cli_wait_for_socket_observes_existing_and_missing_paths(tmp_path: Path) -> None:
    from mcp_broker.cli import _wait_for_socket

    socket_path = tmp_path / "broker.sock"

    assert not _wait_for_socket(socket_path, attempts=1)
    socket_path.touch()
    assert _wait_for_socket(socket_path, attempts=1)


def test_top_level_cli_wait_for_socket_uses_injected_waiter(tmp_path: Path) -> None:
    from mcp_broker.cli import _wait_for_socket

    socket_path = tmp_path / "broker.sock"
    waits: list[float] = []

    assert not _wait_for_socket(socket_path, attempts=3, wait=waits.append)

    assert waits == [0.1, 0.1]


def test_top_level_cli_default_paths_can_use_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.cli import default_config_path, default_runtime_root, default_socket_path

    runtime_root = tmp_path / "runtime"
    socket_path = tmp_path / "custom.sock"
    config_path = tmp_path / "broker.yaml"
    monkeypatch.setenv("MCP_BROKER_RUNTIME_ROOT", str(runtime_root))
    monkeypatch.setenv("MCP_BROKER_SOCKET", str(socket_path))
    monkeypatch.setenv("MCP_BROKER_CONFIG", str(config_path))

    assert default_runtime_root() == runtime_root
    assert default_socket_path() == socket_path
    assert default_config_path() == config_path


def test_top_level_cli_default_paths_use_home_without_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker.cli import default_config_path, default_runtime_root, default_socket_path

    monkeypatch.delenv("MCP_BROKER_RUNTIME_ROOT", raising=False)
    monkeypatch.delenv("MCP_BROKER_SOCKET", raising=False)
    monkeypatch.delenv("MCP_BROKER_CONFIG", raising=False)

    runtime_root = Path.home() / "mcp" / "mcp-broker"

    assert default_runtime_root() == runtime_root
    assert default_socket_path() == runtime_root / "sockets" / "broker.sock"
    assert default_config_path() == runtime_root / "config" / "broker.yaml"


def test_top_level_cli_template_candidates_use_installed_fallback(tmp_path: Path) -> None:
    from mcp_broker.cli import template_path_from_candidates

    source_template = tmp_path / "missing" / "broker.example.yaml"
    installed_template = tmp_path / "share" / "broker.example.yaml"
    installed_template.parent.mkdir(parents=True)
    installed_template.write_text("runtime: {}\n", encoding="utf-8")

    assert template_path_from_candidates(source_template, installed_template) == installed_template


def test_top_level_cli_template_candidates_return_last_missing_candidate(tmp_path: Path) -> None:
    from mcp_broker.cli import template_path_from_candidates

    source_template = tmp_path / "missing-source" / "broker.example.yaml"
    current_template = tmp_path / "missing-current" / "broker.example.yaml"
    installed_template = tmp_path / "missing-installed" / "broker.example.yaml"

    assert template_path_from_candidates(source_template, current_template, installed_template) == installed_template


def test_top_level_cli_default_template_path_prefers_source_tree_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    source_root = tmp_path / "source"
    source_template = source_root / "config" / "broker.example.yaml"
    current_template = tmp_path / "cwd" / "config" / "broker.example.yaml"
    installed_template = tmp_path / "venv" / "share" / "mcp-broker" / "config" / "broker.example.yaml"
    source_template.parent.mkdir(parents=True)
    current_template.parent.mkdir(parents=True)
    installed_template.parent.mkdir(parents=True)
    source_template.write_text("source: true\n", encoding="utf-8")
    current_template.write_text("current: true\n", encoding="utf-8")
    installed_template.write_text("installed: true\n", encoding="utf-8")

    monkeypatch.chdir(current_template.parents[1])
    monkeypatch.setattr(cli, "__file__", str(source_root / "src" / "mcp_broker" / "cli.py"))
    monkeypatch.setattr(sys, "prefix", str(installed_template.parents[3]))

    assert cli.default_template_path() == source_template


def test_top_level_cli_default_template_path_uses_installed_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    missing_source_root = tmp_path / "source"
    cwd = tmp_path / "cwd"
    installed_template = tmp_path / "venv" / "share" / "mcp-broker" / "config" / "broker.example.yaml"
    cwd.mkdir()
    installed_template.parent.mkdir(parents=True)
    installed_template.write_text("installed: true\n", encoding="utf-8")

    monkeypatch.chdir(cwd)
    monkeypatch.setattr(cli, "__file__", str(missing_source_root / "src" / "mcp_broker" / "cli.py"))
    monkeypatch.setattr(sys, "prefix", str(installed_template.parents[3]))

    assert cli.default_template_path() == installed_template


def test_top_level_cli_default_template_path_uses_current_repo_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    repo_template = tmp_path / "config" / "broker.example.yaml"
    repo_template.parent.mkdir(parents=True)
    repo_template.write_text("runtime: {}\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli,
        "__file__",
        str(tmp_path / "venv" / "site-packages" / "mcp_broker" / "cli.py"),
    )
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "venv"))

    assert cli.default_template_path() == repo_template


def test_top_level_cli_init_force_overwrites_existing_config(tmp_path: Path) -> None:
    from mcp_broker.cli import main

    template_path = tmp_path / "template.yaml"
    config_path = tmp_path / "nested" / "configs" / "broker.yaml"
    template_path.write_text("runtime: {}\n", encoding="utf-8")
    config_path.parent.mkdir(parents=True)
    config_path.write_text("existing: true\n", encoding="utf-8")

    assert main(["init", "--config", str(config_path), "--template", str(template_path), "--force"]) == 0

    assert config_path.read_text(encoding="utf-8") == "runtime: {}\n"


def test_top_level_cli_initialize_config_creates_nested_parent_dirs(tmp_path: Path) -> None:
    from mcp_broker.cli import initialize_config

    template_path = tmp_path / "template.yaml"
    config_path = tmp_path / "a" / "b" / "broker.yaml"
    template_path.write_text("runtime: {}\n", encoding="utf-8")

    assert initialize_config(config_path, template_path=template_path, force=False) == 0

    assert config_path.read_text(encoding="utf-8") == "runtime: {}\n"


def test_top_level_cli_init_reports_missing_template(tmp_path: Path) -> None:
    from mcp_broker.cli import main

    assert (
        main(
            [
                "init",
                "--config",
                str(tmp_path / "broker.yaml"),
                "--template",
                str(tmp_path / "missing.yaml"),
            ]
        )
        == 1
    )


def test_top_level_cli_daemon_handler_delegates_constructed_args(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    calls: list[list[str]] = []

    def daemon_runner(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr(cli, "daemon_main", daemon_runner)

    assert cli.main(["status", "--runtime-root", str(tmp_path), "--socket-path", str(tmp_path / "sock")]) == 0

    assert calls == [
        [
            "status",
            "--runtime-root",
            str(tmp_path),
            "--socket-path",
            str(tmp_path / "sock"),
        ]
    ]


def test_top_level_cli_daemon_handler_start_passes_config_but_status_and_stop_do_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    calls: list[list[str]] = []

    def daemon_runner(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    monkeypatch.setattr(cli, "daemon_main", daemon_runner)

    assert (
        cli.main(
            [
                "start",
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(tmp_path / "broker.sock"),
                "--config",
                str(tmp_path / "broker.yaml"),
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "status",
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(tmp_path / "broker.sock"),
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "stop",
                "--runtime-root",
                str(tmp_path / "runtime"),
                "--socket-path",
                str(tmp_path / "broker.sock"),
            ]
        )
        == 0
    )

    assert calls == [
        [
            "serve",
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--socket-path",
            str(tmp_path / "broker.sock"),
            "--config",
            str(tmp_path / "broker.yaml"),
        ],
        [
            "status",
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--socket-path",
            str(tmp_path / "broker.sock"),
        ],
        [
            "stop",
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--socket-path",
            str(tmp_path / "broker.sock"),
        ],
    ]


def test_top_level_cli_daemon_argv_ignores_config_for_non_serve_commands(tmp_path: Path) -> None:
    from mcp_broker.cli import daemon_argv

    assert daemon_argv(
        command="status",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "broker.sock",
        config_path=tmp_path / "broker.yaml",
    ) == [
        "status",
        "--runtime-root",
        str(tmp_path / "runtime"),
        "--socket-path",
        str(tmp_path / "broker.sock"),
    ]


def test_top_level_cli_render_apply_delegates_target_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_broker import cli

    calls: list[list[str]] = []

    def render_runner(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    config_path = tmp_path / "broker.yaml"
    target_path = tmp_path / "client.toml"
    monkeypatch.setattr(cli, "config_render_main", render_runner)

    assert (
        cli.main(
            [
                "render",
                "generic-client",
                "--config",
                str(config_path),
                "--apply",
                "--target-path",
                str(target_path),
            ]
        )
        == 0
    )

    assert calls == [
        [
            "render",
            "--config",
            str(config_path),
            "--client",
            "generic-client",
            "--apply",
            "--target-path",
            str(target_path),
        ]
    ]


class _BinaryConsole:
    def __init__(self, payload: bytes = b"") -> None:
        self.buffer = BytesIO(payload)
        self.text = ""

    def write(self, text: str) -> int:
        self.text += text
        return len(text)

    def flush(self) -> None:
        return None


def _stdio_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "broker.yaml"
    runtime_root = tmp_path / "runtime"
    config_path.write_text(
        f"""
runtime:
  root: {runtime_root}
  socket_path: {_stdio_socket(tmp_path)}
  state_dir: {runtime_root / "state"}
broker:
  tool_namespace_separator: "."
profiles:
  generic-client:
    max_tools: 200
    compact_tools_enabled: false
upstreams: {{}}
""".strip(),
        encoding="utf-8",
    )
    return config_path


def _stdio_socket(tmp_path: Path) -> Path:
    return Path("/tmp") / f"mcp-broker-cli-{os.getpid()}-{tmp_path.name}.sock"
