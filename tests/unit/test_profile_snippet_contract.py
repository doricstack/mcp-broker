import pytest


pytestmark = pytest.mark.unit


def test_profile_snippet_prints_generic_profile_client_and_commands() -> None:
    from mcp_broker.profile_snippet import profile_snippet_text

    text = profile_snippet_text(
        profile_name="local-client",
        client_format="mcp-settings-json",
        config_path="$HOME/.local-client/settings.json",
    )

    assert text == (
        "# Add this under profiles:\n"
        "profiles:\n"
        "  local-client:\n"
        "    max_tools: 80\n"
        "    compact_tools_enabled: true\n"
        "    broker_tool_name_style: dotted\n"
        "\n"
        "# Add this under clients:\n"
        "clients:\n"
        "  local-client:\n"
        "    format: mcp-settings-json\n"
        "    config_path: $HOME/.local-client/settings.json\n"
        "    entry_name: mcp-broker\n"
        "    command: mcp-broker-client\n"
        "    mcp_allowed_servers:\n"
        "      - mcp-broker\n"
        "    args:\n"
        "      - --socket-path\n"
        "      - \"{runtime.socket_path}\"\n"
        "      - --profile\n"
        "      - local-client\n"
        "\n"
        "# Add this profile name to each upstream that should be visible:\n"
        "upstreams:\n"
        "  example-upstream:\n"
        "    profiles:\n"
        "      - local-client\n"
        "\n"
        "# Then run:\n"
        "make config-render CLIENT=local-client CONFIG_RENDER_APPLY=0\n"
        "make profile-validation PROFILE=local-client\n"
    )


def test_profile_snippet_omits_mcp_allowed_servers_for_non_mcp_settings_format() -> None:
    from mcp_broker.profile_snippet import profile_snippet_text

    text = profile_snippet_text(
        profile_name="local-client",
        client_format="codex-toml",
        config_path="$HOME/.codex/config.toml",
        entry_name="broker-entry",
        command="custom-broker-client",
        broker_tool_name_style="snake",
    )

    assert "    mcp_allowed_servers:\n" not in text
    assert "    entry_name: broker-entry\n" in text
    assert "    command: custom-broker-client\n" in text
    assert "    broker_tool_name_style: snake\n" in text


def test_profile_snippet_rejects_invalid_profile_name() -> None:
    from mcp_broker.profile_snippet import profile_snippet_text

    with pytest.raises(ValueError) as exc_info:
        profile_snippet_text(
            profile_name="bad profile",
            client_format="mcp-settings-json",
            config_path="$HOME/.bad/settings.json",
        )
    assert str(exc_info.value) == "profile name must contain only letters, numbers, underscore, or hyphen"


def test_profile_snippet_rejects_unknown_format() -> None:
    from mcp_broker.profile_snippet import profile_snippet_text

    with pytest.raises(ValueError) as exc_info:
        profile_snippet_text(
            profile_name="local-client",
            client_format="yaml",
            config_path="$HOME/.local-client/settings.yaml",
        )
    assert str(exc_info.value) == (
        "client format must be one of: claude-json, codex-toml, mcp-settings-json"
    )


def test_profile_snippet_rejects_unknown_broker_tool_name_style() -> None:
    from mcp_broker.profile_snippet import profile_snippet_text

    with pytest.raises(ValueError) as exc_info:
        profile_snippet_text(
            profile_name="local-client",
            client_format="mcp-settings-json",
            config_path="$HOME/.local-client/settings.json",
            broker_tool_name_style="camel",
        )
    assert str(exc_info.value) == "broker tool name style must be one of: dotted, snake"


def test_profile_snippet_rejects_empty_config_path() -> None:
    from mcp_broker.profile_snippet import profile_snippet_text

    with pytest.raises(ValueError) as exc_info:
        profile_snippet_text(
            profile_name="local-client",
            client_format="mcp-settings-json",
            config_path="",
        )
    assert str(exc_info.value) == "config path must not be empty"


def test_profile_snippet_main_prints_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.profile_snippet import main

    result = main(
        [
            "--profile",
            "local-client",
            "--client-format",
            "mcp-settings-json",
            "--config-path",
            "$HOME/.local-client/settings.json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "    entry_name: mcp-broker\n" in captured.out
    assert "    command: mcp-broker-client\n" in captured.out
    assert "CLIENT=local-client" in captured.out
    assert captured.err == ""


def test_profile_snippet_main_prints_custom_entry_command_and_style(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.profile_snippet import main

    result = main(
        [
            "--profile",
            "local-client",
            "--client-format",
            "codex-toml",
            "--config-path",
            "$HOME/.codex/config.toml",
            "--entry-name",
            "broker-entry",
            "--command",
            "custom-broker-client",
            "--broker-tool-name-style",
            "snake",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "    broker_tool_name_style: snake\n" in captured.out
    assert "    entry_name: broker-entry\n" in captured.out
    assert "    command: custom-broker-client\n" in captured.out
    assert "    mcp_allowed_servers:\n" not in captured.out


def test_profile_snippet_main_reports_validation_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.profile_snippet import main

    result = main(
        [
            "--profile",
            "bad profile",
            "--client-format",
            "mcp-settings-json",
            "--config-path",
            "$HOME/.bad/settings.json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.err == "profile name must contain only letters, numbers, underscore, or hyphen\n"


def test_profile_snippet_main_argparse_guards(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from mcp_broker.profile_snippet import main

    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    captured = capsys.readouterr()
    assert help_exit.value.code == 0
    assert "\nPrint a profile and client config snippet\n\noptions:" in captured.out

    with pytest.raises(SystemExit) as missing_required:
        main([])
    captured = capsys.readouterr()
    assert missing_required.value.code == 2
    assert (
        "the following arguments are required: --profile, --client-format, --config-path"
        in captured.err
    )
