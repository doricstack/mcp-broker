from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.unit


def test_linux_mutation_script_streams_container_output_to_host_log() -> None:
    script = (ROOT / "scripts" / "linux-mutation.sh").read_text(encoding="utf-8")

    assert 'LOG_PATH="${MCP_BROKER_MUTATION_LOG:-$ROOT/var/quality/mutation-linux.log}"' in script
    assert 'mkdir -p "$(dirname "$LOG_PATH")"' in script
    assert 'rm -f "$LOG_PATH"' in script
    assert '2>&1 | tee "$LOG_PATH"' in script
    assert 'printf "linux_mutation=true image=%s stats=%s log=%s\\n"' in script


def test_linux_mutation_script_preserves_caller_supplied_work_dir() -> None:
    script = (ROOT / "scripts" / "linux-mutation.sh").read_text(encoding="utf-8")

    assert "WORK_DIR_CREATED=0" in script
    assert 'WORK_DIR_CREATED=1' in script
    assert 'if [[ "$WORK_DIR_CREATED" == "1" ]]; then' in script
    assert 'rm -rf "$WORK_DIR"' in script


def test_linux_mutation_script_exports_container_mutants_for_debugging() -> None:
    script = (ROOT / "scripts" / "linux-mutation.sh").read_text(encoding="utf-8")

    assert (
        'MUTANTS_EXPORT_DIR="${MCP_BROKER_MUTATION_MUTANTS_DIR:-$ROOT/var/quality/mutants-linux}"'
        in script
    )
    assert 'rm -rf "$MUTANTS_EXPORT_DIR"' in script
    assert 'mkdir -p "$MUTANTS_EXPORT_DIR"' in script
    assert '-v "$MUTANTS_EXPORT_DIR:/mutants-output"' in script
    assert 'copy_mutants()' in script
    assert 'trap copy_mutants EXIT' in script
    assert 'cp -a /workspace/mutants/. /mutants-output/' in script
