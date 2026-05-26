import re
import subprocess
from pathlib import Path

import pytest

from tests.support.repo_paths import make_command

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]


def test_make_help_exposes_broker_entrypoints() -> None:
    result = subprocess.run(
        ["make", "help"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    for target in [
        "setup",
        "test",
        "test-unit",
        "test-journey",
        "test-live",
        "test-e2e",
        "broker-start",
        "broker-stop",
        "broker-status",
        "broker-wait",
        "broker-reap",
        "broker-smoke",
        "tools-count",
        "facade-smoke",
        "codex-facade-smoke",
        "claude-facade-smoke",
        "gemini-facade-smoke",
        "discovery-parity",
        "codex-claude-discovery-parity",
        "launchagent-install",
        "launchagent-load",
        "launchagent-uninstall",
        "launchagent-unload",
        "systemd-install",
        "systemd-load",
        "systemd-uninstall",
        "systemd-unload",
        "windows-install",
        "windows-load",
        "windows-uninstall",
        "windows-unload",
        "linux-container-smoke",
        "linux-release-gate",
        "windows-powershell-smoke",
        "release-smoke",
        "docker-build",
        "docker-smoke",
        "docker-buildx",
        "mcpb-validate",
        "config-init",
        "config-backup",
        "codex-app-policy",
        "config-render",
        "config-rollback",
        "profile-snippet",
        "mutation",
        "mutation-linux",
        "precommit",
        "quality-gate",
        "release-gate",
    ]:
        assert target in result.stdout

    for maintainer_only_target in [
        "codex-deferred-acceptance",
        "public-export",
        "public-export-check",
        "public-release-dry-run",
        "violations",
        "grade-quality",
        "maintainer-violations",
        "maintainer-grade-quality",
        "maintainer-precommit",
        "maintainer-quality-gate",
        "maintainer-release-gate",
    ]:
        assert maintainer_only_target not in result.stdout


def test_make_profile_snippet_keeps_home_placeholder_public_safe() -> None:
    result = subprocess.run(
        make_command(
            "profile-snippet",
            "NEW_PROFILE=sample-client",
            "NEW_CLIENT_FORMAT=mcp-settings-json",
        ),
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert "config_path: $HOME/.sample-client/settings.json" in result.stdout
    assert "mcp_allowed_servers:" in result.stdout
    assert "      - mcp-broker" in result.stdout
    assert "/Users/" not in result.stdout
    assert "make config-render CLIENT=sample-client CONFIG_RENDER_APPLY=0" in result.stdout


def test_mutation_target_uses_venv_console_script() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    setup_cfg = (ROOT / "setup.cfg").read_text(encoding="utf-8")

    mutation_section = makefile.split("mutation: deps", maxsplit=1)[1].split(
        "release-gate:",
        maxsplit=1,
    )[0]
    assert "$(MUTMUT) run" in mutation_section
    assert "python -m mutmut" not in mutation_section
    assert 'MCP_BROKER_REPO_ROOT="$(ROOT)"' not in mutation_section
    assert 'PYTHONPATH="$(PYTHONPATH)"' not in mutation_section
    assert "scripts/check_mutation_stats.py" in mutation_section
    assert '$(if $(MUTATION_ARGS),--include-mutants $(MUTATION_ARGS),)' in mutation_section
    assert "mutation-linux:" in makefile
    assert "scripts/linux-mutation.sh" in makefile
    assert "MUTATION_LOG ?= $(QUALITY_DIR)/mutation-linux.log" in makefile
    assert "MUTATION_MUTANTS_DIR ?= $(QUALITY_DIR)/mutants-linux" in makefile
    assert 'MCP_BROKER_MUTATION_LOG="$(MUTATION_LOG)"' in makefile
    assert 'MCP_BROKER_MUTATION_MUTANTS_DIR="$(MUTATION_MUTANTS_DIR)"' in makefile
    assert "RELEASE_MUTATION_TARGET ?= $(if $(filter Darwin,$(UNAME_S)),mutation-linux,mutation)" in makefile
    assert 'MUTATION_STATS_JSON ?= $(QUALITY_DIR)/mutation_stats.json' in makefile
    assert (
        "MUTATION_FAIL_STATUSES ?= survived no_tests skipped suspicious timeout "
        "check_was_interrupted_by_user segfault not_checked"
    ) in makefile
    assert "release-gate: quality-gate package-check release-smoke $(RELEASE_MUTATION_TARGET)" in makefile
    assert "paths_to_mutate=src/mcp_broker" in setup_cfg
    assert (
        "also_copy=\n"
        "    config\n"
        "    docs\n"
        "    docker\n"
        "    mcpb\n"
        "    registry\n"
        "    scripts\n"
        "    .github\n"
        "    .well-known\n"
        "    .dockerignore\n"
        "    CHANGELOG.md\n"
        "    CONTRIBUTING.md\n"
        "    LICENSE\n"
        "    ROADMAP.md\n"
        "    SECURITY.md\n"
        "    Dockerfile\n"
        "    Makefile\n"
        "    pyproject.toml\n"
        "    pytest.ini\n"
        "    README.md\n"
        "    requirements.txt"
    ) in setup_cfg
    assert "    AGENTS.md" not in setup_cfg
    assert "    TODO.md" not in setup_cfg
    assert "tests_dir=\n    tests/unit\n    tests/journey" in setup_cfg
    assert "pytest_add_cli_args=\n    --timeout=30\n    -m\n    not private_contract" in setup_cfg
    assert "mutate_only_covered_lines=true" in setup_cfg


def test_hidden_maintainer_violations_target_is_public_safe() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "maintainer-violations:" in makefile
    assert "maintainer-grade-quality:" in makefile
    assert "require-violations-tool:" in makefile
    assert "require-grade-quality-tool:" in makefile
    assert "CHECK_VIOLATIONS ?= $(SHARED_SCRIPTS_DIR)/check-violations.sh" in makefile
    assert "GRADE_QUALITY    ?= $(SHARED_SCRIPTS_DIR)/grade_quality.sh" in makefile
    assert "GRADE_REPORT_JSON ?= $(QUALITY_DIR)/grade_quality_report.json" in makefile
    assert "VIOLATIONS_JSON   ?= $(QUALITY_DIR)/violations.json" in makefile
    assert "VIOLATIONS_LOG    ?= $(QUALITY_DIR)/violations.log" in makefile
    assert '--log-file "$(VIOLATIONS_LOG)"' in makefile
    assert '--json-file "$(VIOLATIONS_JSON)"' in makefile
    assert '--violations-json "$(VIOLATIONS_JSON)"' in makefile
    assert '--output-json "$(GRADE_REPORT_JSON)"' in makefile
    assert "~/.llm-shared" not in makefile


def test_live_tests_use_timeout_budget_that_can_cover_configured_upstreams() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    live_section = makefile.split("test-live:", maxsplit=1)[1].split(
        "test-e2e:",
        maxsplit=1,
    )[0]
    coverage_section = makefile.split("test-cov:", maxsplit=1)[1].split(
        "runtime-layout:",
        maxsplit=1,
    )[0]
    live_timeout = re.search(r"^PYTEST_LIVE_TIMEOUT \?= (?P<seconds>\d+)$", makefile, re.MULTILINE)
    coverage_timeout = re.search(
        r"^PYTEST_COV_TIMEOUT \?= \$\(PYTEST_LIVE_TIMEOUT\)$",
        makefile,
        re.MULTILINE,
    )

    assert live_timeout is not None
    assert coverage_timeout is not None
    assert int(live_timeout.group("seconds")) > 60
    assert "PYTEST_LIVE_COMMON" in makefile
    assert "PYTEST_COV_COMMON" in makefile
    assert "$(PYTEST_LIVE_COMMON) $(PYTEST_LIVE_TARGETS)" in live_section
    assert "$(PYTEST_COMMON) $(PYTEST_LIVE_TARGETS)" not in live_section
    assert "$(PYTEST_COV_COMMON)" in coverage_section
    assert "$(PYTEST_COMMON)" not in coverage_section


def test_deps_installs_public_example_for_editable_cli() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    deps_section = makefile.split("deps: $(VENV_DIR)/bin/python", maxsplit=1)[1].split(
        "config-init:",
        maxsplit=1,
    )[0]
    assert "$(VENV_DIR)/share/mcp-broker/config" in deps_section
    assert 'cp "$(CONFIG_TEMPLATE_PATH)" "$(VENV_DIR)/share/mcp-broker/config/broker.example.yaml"' in deps_section
