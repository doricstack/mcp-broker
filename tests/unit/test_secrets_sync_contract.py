import stat
import logging
import runpy
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from mcp_broker import secrets_sync


pytestmark = [pytest.mark.unit, pytest.mark.error_simulation]


@dataclass
class _Runtime:
    secrets_dir: Path


@dataclass
class _Upstream:
    env_files: dict[str, Path] = field(default_factory=dict)


@dataclass
class _Config:
    runtime: _Runtime
    upstreams: dict[str, _Upstream]


def _config(secrets_dir: Path, upstreams: dict[str, _Upstream]) -> _Config:
    return _Config(runtime=_Runtime(secrets_dir=secrets_dir), upstreams=upstreams)


def _write_minimal_config(tmp_path: Path, upstreams_yaml: str = "{}") -> Path:
    runtime_root = tmp_path / "runtime"
    config_path = tmp_path / "broker.yaml"
    config_path.write_text(
        f"""
runtime:
  root: {runtime_root}
  socket_path: {runtime_root}/sockets/broker.sock
  log_dir: {runtime_root}/logs
  state_dir: {runtime_root}/state
  secrets_dir: {runtime_root}/secrets
broker: {{}}
upstreams: {upstreams_yaml}
""",
        encoding="utf-8",
    )
    return config_path


def test_collect_targets_only_includes_paths_under_secrets_dir(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    inside = secrets_dir / "SUPABASE_ACCESS_TOKEN_BFAI"
    outside = tmp_path / "elsewhere" / "OTHER_TOKEN"
    config = _config(
        secrets_dir,
        {
            "service_a": _Upstream({"SUPABASE_ACCESS_TOKEN": inside}),
            "weird": _Upstream({"OTHER_TOKEN": outside}),
        },
    )

    targets = secrets_sync.collect_secret_targets(config)

    assert targets == {"SUPABASE_ACCESS_TOKEN_BFAI": inside}


def test_collect_targets_rejects_paths_that_escape_secrets_dir_after_resolution(
    tmp_path: Path,
) -> None:
    secrets_dir = tmp_path / "secrets"
    escaped = secrets_dir / ".." / "outside" / "ESCAPED_TOKEN"
    config = _config(
        secrets_dir,
        {"service": _Upstream({"ESCAPED_TOKEN": escaped})},
    )

    targets = secrets_sync.collect_secret_targets(config)

    assert targets == {}


def test_collect_targets_uses_store_filename_and_deduplicates_shared_paths(
    tmp_path: Path,
) -> None:
    secrets_dir = tmp_path / "secrets"
    shared = secrets_dir / "nested" / "SHARED_RUNTIME_TOKEN"
    config = _config(
        secrets_dir,
        {
            "service_a": _Upstream({"SOURCE_A": shared}),
            "service_b": _Upstream({"SOURCE_B": shared}),
            "service_c": _Upstream({"OTHER_SOURCE": secrets_dir / "OTHER_RUNTIME_TOKEN"}),
        },
    )

    targets = secrets_sync.collect_secret_targets(config)

    assert targets == {
        "OTHER_RUNTIME_TOKEN": secrets_dir / "OTHER_RUNTIME_TOKEN",
        "SHARED_RUNTIME_TOKEN": shared,
    }


def test_collect_targets_continues_after_one_external_path_in_same_upstream(
    tmp_path: Path,
) -> None:
    secrets_dir = tmp_path / "secrets"
    inside = secrets_dir / "VALID_TOKEN"
    outside = tmp_path / "elsewhere" / "EXTERNAL_TOKEN"
    config = _config(
        secrets_dir,
        {
            "service": _Upstream(
                {
                    "EXTERNAL_SOURCE": outside,
                    "VALID_SOURCE": inside,
                }
            ),
        },
    )

    targets = secrets_sync.collect_secret_targets(config)

    assert targets == {"VALID_TOKEN": inside}


def test_sync_imports_present_and_skips_missing(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    token = secrets_dir / "SUPABASE_ACCESS_TOKEN_BFAI"
    missing = secrets_dir / "FLY_API_TOKEN_BFAI"
    config = _config(
        secrets_dir,
        {
            "service_a": _Upstream({"SUPABASE_ACCESS_TOKEN": token}),
            "service_b": _Upstream({"FLY_API_TOKEN": missing}),
        },
    )
    environ = {"SUPABASE_ACCESS_TOKEN_BFAI": "secret-value\n"}

    imported, skipped = secrets_sync.sync_secrets(config, environ=environ)

    assert imported == ["SUPABASE_ACCESS_TOKEN_BFAI"]
    assert skipped == ["FLY_API_TOKEN_BFAI"]
    assert token.read_text(encoding="utf-8") == "secret-value\n"
    assert not missing.exists()
    mode = stat.S_IMODE(token.stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_sync_orders_targets_by_runtime_secret_name_and_creates_nested_parents(
    tmp_path: Path,
) -> None:
    secrets_dir = tmp_path / "secrets"
    alpha = secrets_dir / "nested" / "ALPHA_TOKEN"
    beta = secrets_dir / "BETA_TOKEN"
    config = _config(
        secrets_dir,
        {
            "service_b": _Upstream({"SOURCE_B": beta}),
            "service_a": _Upstream({"SOURCE_A": alpha}),
        },
    )

    imported, skipped = secrets_sync.sync_secrets(
        config,
        environ={"BETA_TOKEN": "beta", "ALPHA_TOKEN": "alpha"},
    )

    assert imported == ["ALPHA_TOKEN", "BETA_TOKEN"]
    assert skipped == []
    assert alpha.read_text(encoding="utf-8") == "alpha\n"
    assert beta.read_text(encoding="utf-8") == "beta\n"
    assert stat.S_IMODE(alpha.stat().st_mode) == 0o600
    assert stat.S_IMODE(beta.stat().st_mode) == 0o600


def test_sync_strips_only_trailing_newlines_from_secret_values(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    token = secrets_dir / "SERVICE_TOKEN"
    config = _config(
        secrets_dir,
        {"service": _Upstream({"SOURCE_TOKEN": token})},
    )

    imported, skipped = secrets_sync.sync_secrets(
        config,
        environ={"SERVICE_TOKEN": "  keep surrounding spaces  \r\n\n"},
    )

    assert imported == ["SERVICE_TOKEN"]
    assert skipped == []
    assert token.read_text(encoding="utf-8") == "  keep surrounding spaces  \n"


def test_sync_preserves_trailing_x_before_newline(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    token = secrets_dir / "SERVICE_TOKEN"
    config = _config(
        secrets_dir,
        {"service": _Upstream({"SOURCE_TOKEN": token})},
    )

    imported, skipped = secrets_sync.sync_secrets(
        config,
        environ={"SERVICE_TOKEN": "secretX\r\n"},
    )

    assert imported == ["SERVICE_TOKEN"]
    assert skipped == []
    assert token.read_text(encoding="utf-8") == "secretX\n"


def test_sync_creates_secret_file_with_private_mode_before_final_chmod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets_dir = tmp_path / "secrets"
    token = secrets_dir / "SERVICE_TOKEN"
    config = _config(
        secrets_dir,
        {"service": _Upstream({"SOURCE_TOKEN": token})},
    )
    monkeypatch.setattr(secrets_sync.os, "chmod", lambda _path, _mode: None)

    imported, skipped = secrets_sync.sync_secrets(
        config,
        environ={"SERVICE_TOKEN": "secret"},
    )

    assert imported == ["SERVICE_TOKEN"]
    assert skipped == []
    assert stat.S_IMODE(token.stat().st_mode) == 0o600


def test_sync_missing_env_keeps_existing_store_file_unchanged(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True)
    token = secrets_dir / "OPTIONAL_TOKEN"
    token.write_text("existing\n", encoding="utf-8")
    token.chmod(0o640)
    config = _config(
        secrets_dir,
        {"service": _Upstream({"SOURCE_TOKEN": token})},
    )

    imported, skipped = secrets_sync.sync_secrets(config, environ={})

    assert imported == []
    assert skipped == ["OPTIONAL_TOKEN"]
    assert token.read_text(encoding="utf-8") == "existing\n"
    assert stat.S_IMODE(token.stat().st_mode) == 0o640


def test_sync_treats_empty_env_value_as_missing(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    token = secrets_dir / "UPSTASH_API_KEY_BFAI"
    config = _config(
        secrets_dir,
        {"service_c": _Upstream({"UPSTASH_API_KEY": token})},
    )

    imported, skipped = secrets_sync.sync_secrets(config, environ={"UPSTASH_API_KEY_BFAI": ""})

    assert imported == []
    assert skipped == ["UPSTASH_API_KEY_BFAI"]
    assert not token.exists()


def test_sync_overwrites_stale_value(tmp_path: Path) -> None:
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True)
    token = secrets_dir / "SENTRY_ACCESS_TOKEN_BFAI"
    token.write_text("old\n", encoding="utf-8")
    config = _config(
        secrets_dir,
        {"service_d": _Upstream({"SENTRY_ACCESS_TOKEN": token})},
    )

    imported, _ = secrets_sync.sync_secrets(config, environ={"SENTRY_ACCESS_TOKEN_BFAI": "new"})

    assert imported == ["SENTRY_ACCESS_TOKEN_BFAI"]
    assert token.read_text(encoding="utf-8") == "new\n"


def test_sync_reads_process_environment_when_no_mapping_is_supplied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secrets_dir = tmp_path / "secrets"
    token = secrets_dir / "PROCESS_TOKEN"
    config = _config(
        secrets_dir,
        {"service": _Upstream({"SOURCE_TOKEN": token})},
    )
    monkeypatch.setenv("PROCESS_TOKEN", "from-process-env")

    imported, skipped = secrets_sync.sync_secrets(config)

    assert imported == ["PROCESS_TOKEN"]
    assert skipped == []
    assert token.read_text(encoding="utf-8") == "from-process-env\n"


def test_secrets_sync_main_reports_imported_and_skipped_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=secrets_sync.__name__)
    config_path = tmp_path / "broker.yaml"
    loaded = object()

    def fake_from_file(path: Path) -> object:
        assert path == config_path
        return loaded

    def fake_sync(config: object) -> tuple[list[str], list[str]]:
        assert config is loaded
        return ["SUPABASE_ACCESS_TOKEN_BFAI"], ["FLY_API_TOKEN_BFAI"]

    monkeypatch.setattr(secrets_sync.BrokerConfig, "from_file", fake_from_file)
    monkeypatch.setattr(secrets_sync, "sync_secrets", fake_sync)

    result = secrets_sync.main(["--config", str(config_path)])

    assert result == 0
    assert caplog.messages == [
        "secrets sync: imported 1, skipped 1 (missing from environment)",
        "not in environment, store unchanged: FLY_API_TOKEN_BFAI",
    ]


def test_secrets_sync_main_uses_plain_info_logging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_basic_config(**kwargs: object) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(secrets_sync.logging, "basicConfig", fake_basic_config)
    monkeypatch.setattr(secrets_sync.BrokerConfig, "from_file", lambda _path: object())
    monkeypatch.setattr(secrets_sync, "sync_secrets", lambda _config: ([], []))

    result = secrets_sync.main(["--config", str(tmp_path / "broker.yaml")])

    assert result == 0
    assert calls == [{"level": logging.INFO, "format": "%(message)s"}]


def test_secrets_sync_main_reports_skipped_names_with_stable_separator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=secrets_sync.__name__)
    monkeypatch.setattr(secrets_sync.BrokerConfig, "from_file", lambda _path: object())
    monkeypatch.setattr(
        secrets_sync,
        "sync_secrets",
        lambda _config: ([], ["ALPHA_TOKEN", "BETA_TOKEN"]),
    )

    result = secrets_sync.main(["--config", str(tmp_path / "broker.yaml")])

    assert result == 0
    assert caplog.messages == [
        "secrets sync: imported 0, skipped 2 (missing from environment)",
        "not in environment, store unchanged: ALPHA_TOKEN, BETA_TOKEN",
    ]


def test_secrets_sync_main_skips_missing_detail_when_all_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=secrets_sync.__name__)
    monkeypatch.setattr(secrets_sync.BrokerConfig, "from_file", lambda _path: object())
    monkeypatch.setattr(secrets_sync, "sync_secrets", lambda _config: (["A_TOKEN"], []))

    result = secrets_sync.main(["--config", str(tmp_path / "broker.yaml")])

    assert result == 0
    assert caplog.messages == ["secrets sync: imported 1, skipped 0 (missing from environment)"]


def test_secrets_sync_main_help_documents_config_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        secrets_sync.main(["--help"])

    captured = capsys.readouterr()
    assert exc.value.code == 0
    assert "\nSync declared upstream secrets from the environment" in captured.out
    assert "--config CONFIG" in captured.out
    assert "Path to the broker config file" in captured.out
    assert "XXPath to the broker config fileXX" not in captured.out
    assert "path to the broker config file" not in captured.out
    assert "PATH TO THE BROKER CONFIG FILE" not in captured.out


def test_secrets_sync_main_requires_config_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        secrets_sync.main([])

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "the following arguments are required: --config" in captured.err


def test_secrets_sync_module_entrypoint_writes_plain_info_log_to_stderr(
    tmp_path: Path,
) -> None:
    config_path = _write_minimal_config(tmp_path)

    completed = subprocess.run(
        [sys.executable, "-m", "mcp_broker.secrets_sync", "--config", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == "secrets sync: imported 0, skipped 0 (missing from environment)\n"


def test_secrets_sync_module_entrypoint_reports_skipped_secrets_with_stable_join(
    tmp_path: Path,
) -> None:
    runtime_root = tmp_path / "runtime"
    config_path = _write_minimal_config(
        tmp_path,
        f"""
  service:
    command: service
    mode: disabled
    transport: stdio
    tool_prefix: service
    env_files:
      SOURCE_ALPHA: {runtime_root}/secrets/ALPHA_TOKEN
      SOURCE_BETA: {runtime_root}/secrets/BETA_TOKEN
""",
    )

    completed = subprocess.run(
        [sys.executable, "-m", "mcp_broker.secrets_sync", "--config", str(config_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stdout == ""
    assert completed.stderr == (
        "secrets sync: imported 0, skipped 2 (missing from environment)\n"
        "not in environment, store unchanged: ALPHA_TOKEN, BETA_TOKEN\n"
    )


def test_secrets_sync_module_entrypoint_exits_zero_for_minimal_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_minimal_config(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["mcp_broker.secrets_sync", "--config", str(config_path)],
    )

    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(Path(secrets_sync.__file__)), run_name="__main__")

    assert exc.value.code == 0
