# mcp-broker - central MCP process broker

.PHONY: help setup venv deps config-init config-validate test test-unit test-journey test-live test-e2e test-quick \
        test-cov runtime-layout doctor broker-start broker-stop broker-status broker-wait broker-reap broker-smoke \
        tools-count facade-smoke codex-facade-smoke claude-facade-smoke gemini-facade-smoke profile-validation codex-profile-validation claude-profile-validation gemini-profile-validation discovery-parity codex-claude-discovery-parity codex-deferred-acceptance project-mcp-audit project-mcp-migrate secret-import-env launchagent-install launchagent-load launchagent-uninstall launchagent-unload config-backup config-render codex-app-policy config-rollback \
        profile-snippet systemd-install systemd-load systemd-uninstall systemd-unload windows-install windows-load windows-uninstall windows-unload linux-container-smoke linux-release-gate windows-powershell-smoke release-smoke \
        package-build package-check docker-build docker-smoke docker-buildx mcpb-validate mutation mutation-linux precommit quality-gate release-gate clean

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

# ----------------------------------------------------------------------------
# Central configuration
# ----------------------------------------------------------------------------
ROOT              := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
PYTHON_BIN        ?= python3
VENV_DIR          ?= $(ROOT)/venv-mcp-broker
PYTHON            ?= $(VENV_DIR)/bin/python
PIP               ?= $(VENV_DIR)/bin/pip
MUTMUT            ?= $(VENV_DIR)/bin/mutmut
PIP_UPGRADE       ?= 0
REQUIREMENTS      ?= $(ROOT)/requirements.txt

RUNTIME_ROOT      ?= $(HOME)/mcp/mcp-broker
CONFIG_TEMPLATE_PATH ?= $(ROOT)/config/broker.example.yaml
CONFIG_SCHEMA_PATH ?= $(ROOT)/config/broker.schema.json
CONFIG_PRIVATE_PATH ?= $(ROOT)/config/broker.private.yaml
CONFIG_PATH       ?= $(CONFIG_PRIVATE_PATH)
SOCKET_PATH       ?= $(RUNTIME_ROOT)/sockets/broker.sock
LOG_DIR           ?= $(RUNTIME_ROOT)/logs
STATE_DIR         ?= $(RUNTIME_ROOT)/state
SECRETS_DIR       ?= $(RUNTIME_ROOT)/secrets
CLIENT            ?= codex
PROFILE           ?= codex
NEW_PROFILE       ?= local-client
NEW_CLIENT_FORMAT ?= mcp-settings-json
NEW_CLIENT_CONFIG_PATH ?= $$HOME/.$(NEW_PROFILE)/settings.json
NEW_CLIENT_ENTRY_NAME ?= mcp-broker
NEW_CLIENT_COMMAND ?= mcp-broker-client
NEW_BROKER_TOOL_NAME_STYLE ?= dotted
CONFIG_RENDER_APPLY ?= 0
CONFIG_RENDER_TARGET_PATH ?=
CONFIG_BACKUP_LABEL ?=
CODEX_APP_POLICY_APPLY ?= 0
SECRET_NAME       ?=
FACADE_QUERY      ?=
FACADE_CALL_TOOL  ?=
FACADE_CALL_ARGS  ?=
FACADE_REQUEST_TIMEOUT_SECONDS ?= 70
PARITY_LEFT_PROFILE ?= codex
PARITY_RIGHT_PROFILE ?= claude
DISCOVERY_QUERY   ?= $(FACADE_QUERY)
DISCOVERY_CALL_TOOL ?= $(FACADE_CALL_TOOL)
DISCOVERY_CALL_ARGS ?= $(FACADE_CALL_ARGS)
DEFERRED_ACCEPTANCE_FORMAT ?= markdown
PROJECT_MCP_ROOTS ?= $(HOME)/Projects
PROJECT_MCP_BACKUP_ROOT ?= $(RUNTIME_ROOT)/backups/project-mcp
PROJECT_MCP_APPLY ?= 0
PROJECT_MCP_IMPORT_MISSING ?= 0
PROJECT_MCP_PROFILES ?= codex claude
PROJECT_MCP_CLAUDE_CONFIG ?= $(HOME)/.claude.json
LAUNCHAGENT_APPLY ?= 0
LAUNCHAGENT_LABEL ?= com.mcp-broker.agent
LAUNCHAGENT_DOMAIN ?= gui/$(shell id -u)
LAUNCHAGENT_PLIST ?= $(HOME)/Library/LaunchAgents/$(LAUNCHAGENT_LABEL).plist
SYSTEMD_APPLY    ?= 0
SYSTEMD_SERVICE  ?= mcp-broker.service
SYSTEMD_USER_DIR ?= $(HOME)/.config/systemd/user
SYSTEMD_SERVICE_PATH ?= $(SYSTEMD_USER_DIR)/$(SYSTEMD_SERVICE)
MCP_BROKER_DAEMON_COMMAND ?=
WINDOWS_APPLY    ?= 0
WINDOWS_TASK     ?= mcp-broker
LINUX_SMOKE_IMAGE ?= $(or $(MCP_BROKER_LINUX_SMOKE_IMAGE),python:3-bookworm)
LINUX_RELEASE_GATE_IMAGE ?= $(or $(MCP_BROKER_LINUX_RELEASE_GATE_IMAGE),python:3.13-bookworm)
UNAME_S           := $(shell uname -s)
RELEASE_MUTATION_TARGET ?= $(if $(filter Darwin,$(UNAME_S)),mutation-linux,mutation)

PYTEST_MAXFAIL    ?= 1
PYTEST_TIMEOUT    ?= 30
PYTEST_LIVE_TIMEOUT ?= 120
PYTEST_COV_TIMEOUT ?= $(PYTEST_LIVE_TIMEOUT)
PYTEST_ARGS       ?=
COV_FAIL_UNDER    ?= 100
COV_SRC           ?= src/mcp_broker
COV_DIR           ?= $(ROOT)/var/coverage
COV_FILE          ?= $(COV_DIR)/.coverage
TEST_LOG_DIR      ?= $(ROOT)/var/test-logs
QUALITY_DIR       ?= $(ROOT)/var/quality
PACKAGE_DIST_DIR  ?= $(ROOT)/dist
DOCKER_IMAGE      ?= mcp-broker:local
DOCKER_PLATFORM   ?=
DOCKER_PLATFORMS  ?= linux/amd64,linux/arm64
DOCKER_PUSH       ?= 0
DOCKER_SBOM       ?= true
DOCKER_PROVENANCE ?= true
DOCKER_SOURCE_URL ?= https://github.com/NavinAgrawal/mcp-broker
PACKAGE_VERSION   ?= $(shell PYTHONPATH="$(ROOT)/src" "$(PYTHON_BIN)" -c 'import mcp_broker; print(mcp_broker.__version__)')
MCPB_MANIFEST     ?= $(ROOT)/mcpb/manifest.json
PYTEST_COMMON     ?= --color=yes --force-sugar --maxfail=$(PYTEST_MAXFAIL) --timeout=$(PYTEST_TIMEOUT)
PYTEST_LIVE_COMMON ?= --color=yes --force-sugar --maxfail=$(PYTEST_MAXFAIL) --timeout=$(PYTEST_LIVE_TIMEOUT)
PYTEST_COV_COMMON ?= --color=yes --force-sugar --maxfail=$(PYTEST_MAXFAIL) --timeout=$(PYTEST_COV_TIMEOUT)
BROKER_WAIT_SECONDS ?= 10
MUTATION_MAX_CHILDREN ?= 4
MUTATION_ARGS    ?=
MUTATION_IMAGE   ?= python:3.11-bookworm
MUTATION_STATS_JSON ?= $(QUALITY_DIR)/mutation_stats.json
MUTATION_LOG ?= $(QUALITY_DIR)/mutation-linux.log
MUTATION_MUTANTS_DIR ?= $(QUALITY_DIR)/mutants-linux
MUTATION_MIN_SCORE ?= 100
MUTATION_FAIL_STATUSES ?= survived no_tests skipped suspicious timeout check_was_interrupted_by_user segfault not_checked

PY_UNIT_DIR       ?= tests/unit
PY_JOURNEY_DIR    ?= tests/journey
PY_LIVE_DIR       ?= tests/live
PY_E2E_DIR        ?= tests/e2e
PYTEST_UNIT_TARGETS ?= $(if $(PYTEST_ARGS),$(PYTEST_ARGS),$(PY_UNIT_DIR))
PYTEST_JOURNEY_TARGETS ?= $(if $(PYTEST_ARGS),$(PYTEST_ARGS),$(PY_JOURNEY_DIR))
PYTEST_LIVE_TARGETS ?= $(if $(PYTEST_ARGS),$(PYTEST_ARGS),$(PY_LIVE_DIR))
PYTEST_E2E_TARGETS ?= $(if $(PYTEST_ARGS),$(PYTEST_ARGS),$(PY_E2E_DIR))

export PYTHONPATH := $(ROOT)/src
export COVERAGE_FILE := $(COV_FILE)
export MCP_BROKER_RUNTIME_ROOT := $(RUNTIME_ROOT)
export MCP_BROKER_CONFIG := $(CONFIG_PATH)
export MCP_BROKER_SOCKET := $(SOCKET_PATH)
export MCP_BROKER_LOG_DIR := $(LOG_DIR)
export MCP_BROKER_STATE_DIR := $(STATE_DIR)
export MCP_BROKER_SECRETS_DIR := $(SECRETS_DIR)

strip_quotes = $(subst ",,$(1))

define log
	@printf "\033[1;34m[INFO]\033[0m %s\n" "$(call strip_quotes,$(1))"
endef

define log_success
	@printf "\033[1;32m[OK]\033[0m %s\n" "$(call strip_quotes,$(1))"
endef

define log_error
	@printf "\033[1;31m[ERROR]\033[0m %s\n" "$(call strip_quotes,$(1))" >&2
endef

define log_step
	@printf "\n\033[1;36m=== %s ===\033[0m\n" "$(call strip_quotes,$(1))"
endef

help:
	@echo "mcp-broker targets"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

setup: config-init venv deps doctor ## Create config, venv, deps, and verify runtime layout
	$(call log_success,"Setup complete")

venv: $(VENV_DIR)/bin/python ## Create project venv

$(VENV_DIR)/bin/python:
	$(call log_step,"Creating venv $(VENV_DIR)")
	@$(PYTHON_BIN) -m venv $(VENV_DIR)
	$(call log_success,"Venv ready")

deps: $(VENV_DIR)/bin/python ## Install Python dependencies
	$(call log_step,"Installing dependencies")
	@if [[ "$(PIP_UPGRADE)" == "1" ]]; then $(PIP) install --upgrade pip; fi
	@$(PIP) install -r $(REQUIREMENTS)
	@find "$(VENV_DIR)"/lib/python*/site-packages -maxdepth 1 \( -name "mcp_broker-*.dist-info" -o -name "__editable__.mcp_broker-*.pth" \) -exec rm -rf {} +
	@$(PIP) install -e .
	@mkdir -p "$(VENV_DIR)/share/mcp-broker/config"
	@cp "$(CONFIG_TEMPLATE_PATH)" "$(VENV_DIR)/share/mcp-broker/config/broker.example.yaml"
	@touch $(VENV_DIR)/.deps.stamp
	$(call log_success,"Dependencies ready")

config-init: ## Create private runtime config from the public template if missing
	@test -f "$(CONFIG_TEMPLATE_PATH)" || { $(call log_error,"Missing CONFIG_TEMPLATE_PATH=$(CONFIG_TEMPLATE_PATH)"); exit 1; }
	@if [[ -f "$(CONFIG_PRIVATE_PATH)" ]]; then \
		printf "\033[1;32m[OK]\033[0m Private config already exists: %s\n" "$(CONFIG_PRIVATE_PATH)"; \
	else \
		mkdir -p "$$(dirname "$(CONFIG_PRIVATE_PATH)")"; \
		cp "$(CONFIG_TEMPLATE_PATH)" "$(CONFIG_PRIVATE_PATH)" || exit 1; \
		printf "\033[1;32m[OK]\033[0m Created private config: %s\n" "$(CONFIG_PRIVATE_PATH)"; \
	fi

config-validate: runtime-layout ## Validate CONFIG_PATH against the public JSON Schema and runtime loader
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.config_validate \
		--config "$(CONFIG_PATH)" \
		--schema "$(CONFIG_SCHEMA_PATH)"
	$(call log_success,"Config validation passed")

test: test-unit test-journey test-live test-e2e ## Run all test tiers

test-unit: ## Run unit tests
	$(call log_step,"Unit tests")
	@mkdir -p $(COV_DIR) $(TEST_LOG_DIR)
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m pytest $(PYTEST_COMMON) $(PYTEST_UNIT_TARGETS)
	$(call log_success,"Unit tests passed")

test-journey: ## Run journey tests
	$(call log_step,"Journey tests")
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m pytest $(PYTEST_COMMON) $(PYTEST_JOURNEY_TARGETS)
	$(call log_success,"Journey tests passed")

test-live: ## Run live tests
	$(call log_step,"Live tests")
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m pytest $(PYTEST_LIVE_COMMON) $(PYTEST_LIVE_TARGETS)
	$(call log_success,"Live tests passed")

test-e2e: ## Run e2e tests
	$(call log_step,"E2E tests")
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m pytest $(PYTEST_COMMON) $(PYTEST_E2E_TARGETS)
	$(call log_success,"E2E tests passed")

test-quick: ## Fast feedback: unit tests only, fail fast
	$(call log_step,"Quick tests")
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m pytest $(PYTEST_COMMON) -x --no-header -q $(PY_UNIT_DIR)
	$(call log_success,"Quick tests passed")

test-cov: ## Run tests with coverage gate
	$(call log_step,"Coverage tests")
	@mkdir -p $(COV_DIR)
	@rm -f $(COV_FILE)
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m pytest $(PYTEST_COV_COMMON) \
		--cov=$(COV_SRC) --cov-branch --cov-report=term-missing --cov-fail-under=$(COV_FAIL_UNDER) tests
	$(call log_success,"Coverage gate passed")

runtime-layout: ## Create configured runtime directories
	$(call log_step,"Runtime layout")
	@MCP_BROKER_RUNTIME_ROOT="$(RUNTIME_ROOT)" "$(ROOT)/scripts/doctor.sh"

doctor: runtime-layout broker-reap ## Verify runtime directories and report broker-owned leftovers
	@test -f "$(CONFIG_PATH)" || { $(call log_error,"Missing CONFIG_PATH=$(CONFIG_PATH)"); exit 1; }
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.doctor --config "$(CONFIG_PATH)"
	$(call log_success,"Runtime layout ready at $(RUNTIME_ROOT)")

broker-start: runtime-layout ## Start broker daemon in the foreground
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.daemon serve --runtime-root "$(RUNTIME_ROOT)" --socket-path "$(SOCKET_PATH)" --config "$(CONFIG_PATH)"

broker-stop: runtime-layout ## Request broker daemon shutdown
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.daemon stop --runtime-root "$(RUNTIME_ROOT)" --socket-path "$(SOCKET_PATH)"

broker-status: runtime-layout ## Query broker daemon health
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.daemon status --runtime-root "$(RUNTIME_ROOT)" --socket-path "$(SOCKET_PATH)"

broker-wait: runtime-layout ## Wait until the broker daemon accepts health checks
	@deadline=$$((SECONDS + $(BROKER_WAIT_SECONDS))); \
	while (( SECONDS <= deadline )); do \
		if PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.daemon status --runtime-root "$(RUNTIME_ROOT)" --socket-path "$(SOCKET_PATH)" >/dev/null 2>&1; then \
			printf "\033[1;32m[OK]\033[0m Broker ready: %s\n" "$(SOCKET_PATH)"; \
			exit 0; \
		fi; \
		sleep 1; \
	done; \
	printf "\033[1;31m[ERROR]\033[0m Broker did not become ready within %s seconds: %s\n" "$(BROKER_WAIT_SECONDS)" "$(SOCKET_PATH)" >&2; \
	exit 1

broker-reap: runtime-layout ## Reap stale broker-owned pidfiles, sockets, and orphaned process groups
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.runtime_reaper --runtime-root "$(RUNTIME_ROOT)"

broker-smoke: runtime-layout ## Run broker wiring safety smoke without writing client configs
	@$(MAKE) --no-print-directory config-render CLIENT=codex CONFIG_RENDER_APPLY=0 RUNTIME_ROOT="$(RUNTIME_ROOT)" SOCKET_PATH="$(SOCKET_PATH)"
	@$(MAKE) --no-print-directory config-render CLIENT=claude CONFIG_RENDER_APPLY=0 RUNTIME_ROOT="$(RUNTIME_ROOT)" SOCKET_PATH="$(SOCKET_PATH)"
	@$(MAKE) --no-print-directory config-render CLIENT=gemini CONFIG_RENDER_APPLY=0 RUNTIME_ROOT="$(RUNTIME_ROOT)" SOCKET_PATH="$(SOCKET_PATH)"
	@$(MAKE) --no-print-directory broker-reap RUNTIME_ROOT="$(RUNTIME_ROOT)" SOCKET_PATH="$(SOCKET_PATH)"
	$(call log_success,"Broker smoke passed")

tools-count: runtime-layout broker-reap ## Count broker-advertised tools for PROFILE
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.tool_count --config "$(CONFIG_PATH)" --profile "$(PROFILE)"

facade-smoke: runtime-layout broker-reap ## Exercise compact broker facade through the client shim for PROFILE
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.facade_smoke \
		--config "$(CONFIG_PATH)" \
		--profile "$(PROFILE)" \
		--query "$(FACADE_QUERY)" \
		--call-tool "$(FACADE_CALL_TOOL)" \
		--call-args '$(FACADE_CALL_ARGS)' \
		--request-timeout-seconds "$(FACADE_REQUEST_TIMEOUT_SECONDS)"

codex-facade-smoke: PROFILE=codex
codex-facade-smoke: facade-smoke ## Exercise compact Codex broker facade through the client shim

claude-facade-smoke: PROFILE=claude
claude-facade-smoke: facade-smoke ## Exercise compact Claude broker facade through the client shim without wiring Claude

gemini-facade-smoke: PROFILE=gemini
gemini-facade-smoke: facade-smoke ## Exercise compact Gemini broker facade profile

profile-validation: runtime-layout broker-reap ## Validate all enabled upstreams for PROFILE using YAML smoke probes
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.profile_validation \
		--config "$(CONFIG_PATH)" \
		--profile "$(PROFILE)"

codex-profile-validation: PROFILE=codex
codex-profile-validation: profile-validation ## Validate every configured Codex upstream through the broker

claude-profile-validation: PROFILE=claude
claude-profile-validation: profile-validation ## Validate every configured Claude upstream without rendering Claude

gemini-profile-validation: PROFILE=gemini
gemini-profile-validation: profile-validation ## Validate every configured Gemini upstream through the broker

discovery-parity: runtime-layout broker-reap ## Compare broker discovery between PARITY_LEFT_PROFILE and PARITY_RIGHT_PROFILE
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.discovery_parity \
		--config "$(CONFIG_PATH)" \
		--left-profile "$(PARITY_LEFT_PROFILE)" \
		--right-profile "$(PARITY_RIGHT_PROFILE)" \
		--query "$(DISCOVERY_QUERY)" \
		--call-tool "$(DISCOVERY_CALL_TOOL)" \
		--call-args '$(DISCOVERY_CALL_ARGS)'

codex-claude-discovery-parity: PARITY_LEFT_PROFILE=codex
codex-claude-discovery-parity: PARITY_RIGHT_PROFILE=claude
codex-claude-discovery-parity: discovery-parity ## Compare Codex and Claude broker discovery without wiring Claude

codex-deferred-acceptance: PROFILE=codex
codex-deferred-acceptance: runtime-layout
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.deferred_acceptance \
		--config "$(CONFIG_PATH)" \
		--profile "$(PROFILE)" \
		--format "$(DEFERRED_ACCEPTANCE_FORMAT)"

secret-import-env: runtime-layout ## Store SECRET_NAME from current environment under runtime secrets
	@test -n "$(SECRET_NAME)" || { $(call log_error,"Set SECRET_NAME"); exit 1; }
	@[[ "$(SECRET_NAME)" =~ ^[A-Za-z_][A-Za-z0-9_]*$$ ]] || { $(call log_error,"SECRET_NAME must be an environment variable name"); exit 1; }
	@VALUE="$$(printenv "$(SECRET_NAME)")"; \
		test -n "$$VALUE" || { $(call log_error,"Environment variable $(SECRET_NAME) is missing or empty"); exit 1; }; \
		umask 077; \
		printf '%s\n' "$$VALUE" > "$(SECRETS_DIR)/$(SECRET_NAME)"
	$(call log_success,"Imported $(SECRET_NAME) into $(SECRETS_DIR)")

launchagent-install: deps runtime-layout ## Render LaunchAgent by default; set LAUNCHAGENT_APPLY=1 to write it
	@if [[ "$(LAUNCHAGENT_APPLY)" == "1" ]]; then \
		APPLY_ARG="--apply"; \
	else \
		APPLY_ARG="--dry-run"; \
	fi; \
	MCP_BROKER_RUNTIME_ROOT="$(RUNTIME_ROOT)" MCP_BROKER_SOCKET="$(SOCKET_PATH)" MCP_BROKER_CONFIG="$(CONFIG_PATH)" "$(ROOT)/scripts/install-launchagent.sh" $$APPLY_ARG

launchagent-load: deps runtime-layout ## Load and kickstart the installed broker LaunchAgent
	@test -f "$(LAUNCHAGENT_PLIST)" || { $(call log_error,"Missing LaunchAgent plist: $(LAUNCHAGENT_PLIST)"); exit 1; }
	@launchctl bootout "$(LAUNCHAGENT_DOMAIN)" "$(LAUNCHAGENT_PLIST)" >/dev/null 2>&1 || true
	@launchctl bootstrap "$(LAUNCHAGENT_DOMAIN)" "$(LAUNCHAGENT_PLIST)"
	@launchctl enable "$(LAUNCHAGENT_DOMAIN)/$(LAUNCHAGENT_LABEL)"
	@launchctl kickstart -k "$(LAUNCHAGENT_DOMAIN)/$(LAUNCHAGENT_LABEL)"
	@$(MAKE) --no-print-directory broker-wait RUNTIME_ROOT="$(RUNTIME_ROOT)" SOCKET_PATH="$(SOCKET_PATH)" BROKER_WAIT_SECONDS="$(BROKER_WAIT_SECONDS)"
	$(call log_success,"LaunchAgent loaded: $(LAUNCHAGENT_LABEL)")

launchagent-uninstall: runtime-layout ## Plan LaunchAgent removal by default; set LAUNCHAGENT_APPLY=1 to remove it
	@if [[ "$(LAUNCHAGENT_APPLY)" == "1" ]]; then \
		APPLY_ARG="--apply"; \
	else \
		APPLY_ARG="--dry-run"; \
	fi; \
	MCP_BROKER_RUNTIME_ROOT="$(RUNTIME_ROOT)" MCP_BROKER_SOCKET="$(SOCKET_PATH)" "$(ROOT)/scripts/uninstall-launchagent.sh" $$APPLY_ARG

launchagent-unload: runtime-layout ## Unload the broker LaunchAgent from launchd
	@launchctl bootout "$(LAUNCHAGENT_DOMAIN)" "$(LAUNCHAGENT_PLIST)" >/dev/null 2>&1 || true
	$(call log_success,"LaunchAgent unloaded: $(LAUNCHAGENT_LABEL)")

systemd-install: deps runtime-layout ## Render systemd user service by default; set SYSTEMD_APPLY=1 to write it
	@if [[ "$(SYSTEMD_APPLY)" == "1" ]]; then \
		APPLY_ARG="--apply"; \
	else \
		APPLY_ARG="--dry-run"; \
	fi; \
	MCP_BROKER_RUNTIME_ROOT="$(RUNTIME_ROOT)" MCP_BROKER_SOCKET="$(SOCKET_PATH)" MCP_BROKER_CONFIG="$(CONFIG_PATH)" MCP_BROKER_DAEMON_COMMAND="$(MCP_BROKER_DAEMON_COMMAND)" MCP_BROKER_SYSTEMD_SERVICE="$(SYSTEMD_SERVICE)" "$(ROOT)/scripts/install-systemd-user.sh" $$APPLY_ARG

systemd-load: deps runtime-layout ## Reload and start the installed systemd user service
	@test -f "$(SYSTEMD_SERVICE_PATH)" || { $(call log_error,"Missing systemd user service: $(SYSTEMD_SERVICE_PATH)"); exit 1; }
	@command -v systemctl >/dev/null 2>&1 || { $(call log_error,"systemctl is required for systemd-load"); exit 1; }
	@systemctl --user daemon-reload
	@systemctl --user enable --now "$(SYSTEMD_SERVICE)"
	$(call log_success,"systemd user service loaded: $(SYSTEMD_SERVICE)")

systemd-uninstall: runtime-layout ## Plan systemd user-service removal by default; set SYSTEMD_APPLY=1 to remove it
	@if [[ "$(SYSTEMD_APPLY)" == "1" ]]; then \
		APPLY_ARG="--apply"; \
	else \
		APPLY_ARG="--dry-run"; \
	fi; \
	MCP_BROKER_RUNTIME_ROOT="$(RUNTIME_ROOT)" MCP_BROKER_SYSTEMD_SERVICE="$(SYSTEMD_SERVICE)" "$(ROOT)/scripts/uninstall-systemd-user.sh" $$APPLY_ARG

systemd-unload: runtime-layout ## Stop and disable the systemd user service
	@command -v systemctl >/dev/null 2>&1 || { $(call log_error,"systemctl is required for systemd-unload"); exit 1; }
	@systemctl --user disable --now "$(SYSTEMD_SERVICE)" >/dev/null 2>&1 || true
	@systemctl --user daemon-reload
	$(call log_success,"systemd user service unloaded: $(SYSTEMD_SERVICE)")

windows-install: runtime-layout ## Render Windows Scheduled Task by default; set WINDOWS_APPLY=1 to register it
	@if [[ "$(WINDOWS_APPLY)" == "1" ]]; then \
		APPLY_ARG="-Apply"; \
	else \
		APPLY_ARG="-DryRun"; \
	fi; \
	if command -v pwsh >/dev/null 2>&1; then \
		PWSH=pwsh; \
	elif command -v powershell.exe >/dev/null 2>&1; then \
		PWSH=powershell.exe; \
	else \
		$(call log_error,"PowerShell is required for windows-install"); exit 1; \
	fi; \
	MCP_BROKER_RUNTIME_ROOT="$(RUNTIME_ROOT)" MCP_BROKER_SOCKET="$(SOCKET_PATH)" MCP_BROKER_CONFIG="$(CONFIG_PATH)" MCP_BROKER_DAEMON_COMMAND="$(MCP_BROKER_DAEMON_COMMAND)" MCP_BROKER_WINDOWS_TASK="$(WINDOWS_TASK)" $$PWSH -NoProfile -ExecutionPolicy Bypass -File "$(ROOT)/scripts/install-windows-task.ps1" $$APPLY_ARG

windows-load: WINDOWS_APPLY=1
windows-load: windows-install ## Register and enable the Windows Scheduled Task
	$(call log_success,"Windows Scheduled Task registered: $(WINDOWS_TASK)")

windows-uninstall: runtime-layout ## Plan Windows Scheduled Task removal by default; set WINDOWS_APPLY=1 to remove it
	@if [[ "$(WINDOWS_APPLY)" == "1" ]]; then \
		APPLY_ARG="-Apply"; \
	else \
		APPLY_ARG="-DryRun"; \
	fi; \
	if command -v pwsh >/dev/null 2>&1; then \
		PWSH=pwsh; \
	elif command -v powershell.exe >/dev/null 2>&1; then \
		PWSH=powershell.exe; \
	else \
		$(call log_error,"PowerShell is required for windows-uninstall"); exit 1; \
	fi; \
	MCP_BROKER_RUNTIME_ROOT="$(RUNTIME_ROOT)" MCP_BROKER_WINDOWS_TASK="$(WINDOWS_TASK)" $$PWSH -NoProfile -ExecutionPolicy Bypass -File "$(ROOT)/scripts/uninstall-windows-task.ps1" $$APPLY_ARG

windows-unload: WINDOWS_APPLY=1
windows-unload: windows-uninstall ## Remove the Windows Scheduled Task

linux-container-smoke: ## Run public setup and systemd dry-run inside a Linux container
	@MCP_BROKER_LINUX_SMOKE_IMAGE="$(LINUX_SMOKE_IMAGE)" "$(ROOT)/scripts/linux-container-smoke.sh"

linux-release-gate: ## Run the PyPI workflow release gate inside Linux
	@MCP_BROKER_LINUX_RELEASE_GATE_IMAGE="$(LINUX_RELEASE_GATE_IMAGE)" "$(ROOT)/scripts/linux-release-gate.sh"

windows-powershell-smoke: ## Run Windows Scheduled Task PowerShell dry-run checks
	@"$(ROOT)/scripts/windows-powershell-smoke.sh"

config-backup: runtime-layout ## Back up one configured client target without rendering or applying config
	@if [[ -n "$(CONFIG_BACKUP_LABEL)" ]]; then \
		LABEL_ARG="--label $(CONFIG_BACKUP_LABEL)"; \
	else \
		LABEL_ARG=""; \
	fi; \
	PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.config_render backup --config "$(CONFIG_PATH)" --client "$(CLIENT)" $$LABEL_ARG

config-render: runtime-layout ## Render one client config to runtime renders; set CONFIG_RENDER_APPLY=1 to write target
	@if [[ "$(CONFIG_RENDER_APPLY)" == "1" ]]; then \
		APPLY_ARG="--apply"; \
	else \
		APPLY_ARG=""; \
	fi; \
	if [[ -n "$(CONFIG_RENDER_TARGET_PATH)" ]]; then \
		TARGET_PATH_ARG=(--target-path "$(CONFIG_RENDER_TARGET_PATH)"); \
	else \
		TARGET_PATH_ARG=(); \
	fi; \
	PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.config_render render --config "$(CONFIG_PATH)" --client "$(CLIENT)" $$APPLY_ARG "$${TARGET_PATH_ARG[@]}"

codex-app-policy: runtime-layout ## Enforce configured Codex app connector policy; set CODEX_APP_POLICY_APPLY=1 to write cache changes
	@if [[ "$(CODEX_APP_POLICY_APPLY)" == "1" ]]; then \
		APPLY_ARG="--apply"; \
	else \
		APPLY_ARG=""; \
	fi; \
	if [[ -n "$(CONFIG_BACKUP_LABEL)" ]]; then \
		LABEL_ARG="--label $(CONFIG_BACKUP_LABEL)"; \
	else \
		LABEL_ARG=""; \
	fi; \
	PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.config_render app-policy --config "$(CONFIG_PATH)" --client "$(CLIENT)" $$APPLY_ARG $$LABEL_ARG

project-mcp-audit: runtime-layout ## Audit project .mcp.json files against broker config
	@ROOT_ARGS=(); \
	for root in $(PROJECT_MCP_ROOTS); do ROOT_ARGS+=(--root "$$root"); done; \
	PROFILE_ARGS=(); \
	for profile in $(PROJECT_MCP_PROFILES); do PROFILE_ARGS+=(--profile "$$profile"); done; \
	if [[ -n "$(PROJECT_MCP_CLAUDE_CONFIG)" && -f "$(PROJECT_MCP_CLAUDE_CONFIG)" ]]; then CLAUDE_ARGS=(--claude-config "$(PROJECT_MCP_CLAUDE_CONFIG)"); else CLAUDE_ARGS=(); fi; \
	PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.project_mcp \
		--config "$(CONFIG_PATH)" \
		--backup-root "$(PROJECT_MCP_BACKUP_ROOT)" \
		"$${ROOT_ARGS[@]}" \
		"$${PROFILE_ARGS[@]}" \
		"$${CLAUDE_ARGS[@]}"

project-mcp-migrate: runtime-layout ## Back up and empty covered project .mcp.json files; set PROJECT_MCP_IMPORT_MISSING=1 to import missing entries
	@ROOT_ARGS=(); \
	for root in $(PROJECT_MCP_ROOTS); do ROOT_ARGS+=(--root "$$root"); done; \
	PROFILE_ARGS=(); \
	for profile in $(PROJECT_MCP_PROFILES); do PROFILE_ARGS+=(--profile "$$profile"); done; \
	if [[ "$(PROJECT_MCP_APPLY)" == "1" ]]; then APPLY_ARG="--apply"; else APPLY_ARG=""; fi; \
	if [[ "$(PROJECT_MCP_IMPORT_MISSING)" == "1" ]]; then IMPORT_ARG="--import-missing"; else IMPORT_ARG=""; fi; \
	if [[ -n "$(PROJECT_MCP_CLAUDE_CONFIG)" && -f "$(PROJECT_MCP_CLAUDE_CONFIG)" ]]; then CLAUDE_ARGS=(--claude-config "$(PROJECT_MCP_CLAUDE_CONFIG)"); else CLAUDE_ARGS=(); fi; \
	PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.project_mcp \
		--config "$(CONFIG_PATH)" \
		--backup-root "$(PROJECT_MCP_BACKUP_ROOT)" \
		"$${ROOT_ARGS[@]}" \
		"$${PROFILE_ARGS[@]}" \
		"$${CLAUDE_ARGS[@]}" \
		$$APPLY_ARG $$IMPORT_ARG

config-rollback: runtime-layout ## Restore latest backup for one client config
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.config_render rollback --config "$(CONFIG_PATH)" --client "$(CLIENT)"

profile-snippet: ## Print a generic profile/client YAML snippet; set NEW_PROFILE and NEW_CLIENT_FORMAT
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.profile_snippet \
		--profile "$(NEW_PROFILE)" \
		--client-format "$(NEW_CLIENT_FORMAT)" \
		--config-path '$(NEW_CLIENT_CONFIG_PATH)' \
		--entry-name "$(NEW_CLIENT_ENTRY_NAME)" \
		--command "$(NEW_CLIENT_COMMAND)" \
		--broker-tool-name-style "$(NEW_BROKER_TOOL_NAME_STYLE)"

release-smoke: ## Run clean-tree public setup smoke from tracked files
	@"$(ROOT)/scripts/release-smoke.sh"

package-build: deps ## Build wheel and source distribution into dist/
	@rm -rf "$(PACKAGE_DIST_DIR)"
	@$(PYTHON) -m build --outdir "$(PACKAGE_DIST_DIR)" "$(ROOT)"
	$(call log_success,"Package artifacts built in $(PACKAGE_DIST_DIR)")

package-check: package-build ## Validate built package metadata
	@$(PYTHON) -m twine check "$(PACKAGE_DIST_DIR)"/*
	$(call log_success,"Package artifacts passed twine check")

docker-build: ## Build the local Docker image
	$(call log_step,"Building Docker image $(DOCKER_IMAGE)")
	@docker build $(if $(DOCKER_PLATFORM),--platform "$(DOCKER_PLATFORM)",) \
		--build-arg VERSION="$(PACKAGE_VERSION)" \
		--build-arg VCS_REF="$$(git -C "$(ROOT)" rev-parse --short HEAD 2>/dev/null || printf unknown)" \
		--build-arg SOURCE_URL="$(DOCKER_SOURCE_URL)" \
		-t "$(DOCKER_IMAGE)" "$(ROOT)"
	$(call log_success,"Docker image built: $(DOCKER_IMAGE)")

docker-smoke: docker-build ## Smoke test the Docker stdio entrypoint
	$(call log_step,"Smoke testing Docker image $(DOCKER_IMAGE)")
	@mkdir -p "$(TEST_LOG_DIR)"
	@printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"docker-smoke","version":"0"}}}\n{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n' | docker run --rm -i "$(DOCKER_IMAGE)" | tee "$(TEST_LOG_DIR)/docker-smoke.jsonl" | grep -q '"tools"'
	$(call log_success,"Docker smoke passed")

docker-buildx: ## Build multi-arch Docker image with SBOM/provenance; set DOCKER_PUSH=1 to push
	$(call log_step,"Building multi-arch Docker image $(DOCKER_IMAGE)")
	@if [[ "$(DOCKER_PUSH)" == "1" ]]; then \
		OUTPUT_ARG="--push"; \
	else \
		OUTPUT_ARG="--load"; \
		if [[ "$(DOCKER_PLATFORMS)" == *,* ]]; then \
			printf "\033[1;31m[ERROR]\033[0m docker-buildx without DOCKER_PUSH=1 supports one platform only; set DOCKER_PLATFORMS=linux/arm64 for local load\n" >&2; \
			exit 1; \
		fi; \
	fi; \
	docker buildx build \
		--platform "$(DOCKER_PLATFORMS)" \
		--build-arg VERSION="$(PACKAGE_VERSION)" \
		--build-arg VCS_REF="$$(git -C "$(ROOT)" rev-parse --short HEAD 2>/dev/null || printf unknown)" \
		--build-arg SOURCE_URL="$(DOCKER_SOURCE_URL)" \
		--sbom=$(DOCKER_SBOM) \
		--provenance=$(DOCKER_PROVENANCE) \
		-t "$(DOCKER_IMAGE)" \
		$$OUTPUT_ARG \
		"$(ROOT)"
	$(call log_success,"Docker buildx completed: $(DOCKER_IMAGE)")

mcpb-validate: ## Validate MCPB manifest metadata
	$(call log_step,"Validating MCPB manifest")
	@npx -y @anthropic-ai/mcpb validate "$(MCPB_MANIFEST)"
	$(call log_success,"MCPB manifest passed")

precommit: test-unit test-journey ## Public commit gate using repo-local checks
	$(call log_success,"Precommit gate passed")

quality-gate: test-cov ## Public quality gate using repo-local tests and coverage
	$(call log_success,"Quality gate passed")

mutation: deps ## Run mutation tests with mutmut
	$(call log_step,"Mutation tests")
	@mkdir -p "$(QUALITY_DIR)"
	@rm -rf "$(ROOT)/.mutmut-cache" "$(ROOT)/mutants" "$(MUTATION_STATS_JSON)"
	@$(MUTMUT) run --max-children $(MUTATION_MAX_CHILDREN) $(MUTATION_ARGS)
	@$(MUTMUT) results
	@$(PYTHON) "$(ROOT)/scripts/check_mutation_stats.py" \
		--mutants-dir "$(ROOT)/mutants" \
		--output-json "$(MUTATION_STATS_JSON)" \
		--min-score "$(MUTATION_MIN_SCORE)" \
		$(if $(MUTATION_ARGS),--include-mutants $(MUTATION_ARGS),) \
		--fail-statuses $(MUTATION_FAIL_STATUSES)
	$(call log_success,"Mutation tests passed")

mutation-linux: ## Run mutation tests inside a Linux container
	@MCP_BROKER_MUTATION_IMAGE="$(MUTATION_IMAGE)" \
		MCP_BROKER_MUTATION_MAX_CHILDREN="$(MUTATION_MAX_CHILDREN)" \
		MCP_BROKER_MUTATION_ARGS="$(MUTATION_ARGS)" \
		MCP_BROKER_MUTATION_LOG="$(MUTATION_LOG)" \
		MCP_BROKER_MUTATION_MUTANTS_DIR="$(MUTATION_MUTANTS_DIR)" \
		"$(ROOT)/scripts/linux-mutation.sh"

release-gate: quality-gate package-check release-smoke $(RELEASE_MUTATION_TARGET) ## Run release gates with mutation last
	$(call log_success,"Release gate passed")

clean: ## Remove generated artifacts
	@rm -rf "$(ROOT)/var/coverage" "$(ROOT)/var/test-logs" "$(ROOT)/var/quality" "$(ROOT)/.pytest_cache" "$(ROOT)/.mutmut-cache" "$(ROOT)/mutants" "$(ROOT)/htmlcov" "$(ROOT)/dist" "$(ROOT)/build"
	@rm -f "$(ROOT)/violations.json" "$(ROOT)/violations.log" "$(ROOT)/grade_quality_report.json"
	$(call log_success,"Clean complete")

-include $(ROOT)/local.mk
