import subprocess
from pathlib import Path

import pytest
import yaml

from tests.support.repo_paths import make_command

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_CONFIG_FILE = ROOT / "config" / "broker.example.yaml"


def test_config_init_creates_generic_private_config_in_custom_path(
    tmp_path: Path,
) -> None:
    private_config = tmp_path / "generated" / "broker.private.yaml"
    runtime_root = tmp_path / "runtime"

    init_result = subprocess.run(
        make_command(
            "config-init",
            f"CONFIG_PRIVATE_PATH={private_config}",
        ),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert init_result.returncode == 0, init_result.stdout + init_result.stderr
    assert "Created private config" in init_result.stdout
    assert private_config.is_file()
    assert private_config.read_text(encoding="utf-8") == PUBLIC_CONFIG_FILE.read_text(
        encoding="utf-8"
    )

    private_text = private_config.read_text(encoding="utf-8")
    private_markers = [
        "/Users/",
        "$HOME/Projects",
        "$HOME/Library",
        "$HOME/Documents",
        "CloudStorage",
    ]
    assert [marker for marker in private_markers if marker in private_text] == []

    loaded = yaml.safe_load(private_text)
    public_loaded = yaml.safe_load(PUBLIC_CONFIG_FILE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    assert isinstance(public_loaded, dict)
    assert sorted(loaded["upstreams"]) == sorted(public_loaded["upstreams"])
    assert all(upstream["enabled"] is False for upstream in loaded["upstreams"].values())

    validate_result = subprocess.run(
        make_command(
            "config-validate",
            f"CONFIG_PATH={private_config}",
            f"CONFIG_PRIVATE_PATH={private_config}",
            f"RUNTIME_ROOT={runtime_root}",
            f"SOCKET_PATH={runtime_root / 'sockets' / 'broker.sock'}",
        ),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert validate_result.returncode == 0, validate_result.stdout + validate_result.stderr
    assert "Config validation passed" in validate_result.stdout
