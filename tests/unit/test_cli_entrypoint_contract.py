import runpy
import sys
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
        "mcp_broker.project_mcp",
        "mcp_broker.runtime_reaper",
        "mcp_broker.tool_count",
    ],
)
def test_cli_module_entrypoints_delegate_to_argparse_help(
    module_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", [module_name, "--help"])
    sys.modules.pop(module_name, None)

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module(module_name, run_name="__main__")

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
    from mcp_broker.cli import daemon_argv

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


def test_top_level_cli_init_force_overwrites_existing_config(tmp_path: Path) -> None:
    from mcp_broker.cli import main

    template_path = tmp_path / "template.yaml"
    config_path = tmp_path / "broker.yaml"
    template_path.write_text("runtime: {}\n", encoding="utf-8")
    config_path.write_text("existing: true\n", encoding="utf-8")

    assert main(["init", "--config", str(config_path), "--template", str(template_path), "--force"]) == 0

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
