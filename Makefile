# mcp-broker - central MCP process broker

.PHONY: help setup venv deps config-init config-validate test test-unit test-journey test-live test-e2e test-quick \
        test-cov runtime-layout doctor broker-start broker-stop broker-status broker-reap broker-smoke \
        tools-count facade-smoke codex-facade-smoke claude-facade-smoke gemini-facade-smoke profile-validation codex-profile-validation claude-profile-validation gemini-profile-validation discovery-parity codex-claude-discovery-parity codex-deferred-acceptance project-mcp-audit project-mcp-migrate secret-import-env launchagent-install launchagent-load launchagent-uninstall launchagent-unload config-backup config-render codex-app-policy config-rollback \
        systemd-install systemd-load systemd-uninstall systemd-unload windows-install windows-load windows-uninstall windows-unload linux-container-smoke windows-powershell-smoke release-smoke \
        public-export public-export-check public-release-dry-run require-maintainer-tools violations grade-quality precommit quality-gate maintainer-violations maintainer-grade-quality maintainer-precommit maintainer-quality-gate clean

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
CONFIG_RENDER_APPLY ?= 0
CONFIG_RENDER_TARGET_PATH ?=
CONFIG_BACKUP_LABEL ?=
CODEX_APP_POLICY_APPLY ?= 0
SECRET_NAME       ?=
FACADE_QUERY      ?= memory
FACADE_CALL_TOOL  ?= memory.get_project_scope
FACADE_CALL_ARGS  ?= {}
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
PUBLIC_REPO       ?= $(ROOT)/var/public-export-check
PUBLIC_EXPORT_ALLOWLIST ?= $(ROOT)/public-export/allowlist.txt
PUBLIC_EXPORT_DENYLIST ?= $(ROOT)/public-export/denylist.txt
PUBLIC_EXPORT_DELETE_STALE ?= 1

PYTEST_MAXFAIL    ?= 1
PYTEST_TIMEOUT    ?= 30
PYTEST_ARGS       ?=
COV_FAIL_UNDER    ?= 100
COV_SRC           ?= src/mcp_broker
COV_DIR           ?= $(ROOT)/var/coverage
COV_FILE          ?= $(COV_DIR)/.coverage
TEST_LOG_DIR      ?= $(ROOT)/var/test-logs
QUALITY_DIR       ?= $(ROOT)/var/quality
VIOLATIONS_JSON   ?= $(QUALITY_DIR)/violations.json
VIOLATIONS_LOG    ?= $(QUALITY_DIR)/violations.log
GRADE_REPORT_JSON ?= $(QUALITY_DIR)/grade_quality_report.json
SHARED_SCRIPTS_DIR ?= $(HOME)/.llm-shared/scripts
CHECK_VIOLATIONS ?= $(SHARED_SCRIPTS_DIR)/check-violations.sh
GRADE_QUALITY    ?= $(SHARED_SCRIPTS_DIR)/grade_quality.sh
GIT_SECURITY_GUARD ?= $(SHARED_SCRIPTS_DIR)/git-security-guard.sh
PYTEST_COMMON     ?= --color=yes --force-sugar --maxfail=$(PYTEST_MAXFAIL) --timeout=$(PYTEST_TIMEOUT)

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

deps: $(VENV_DIR)/.deps.stamp ## Install Python dependencies

$(VENV_DIR)/.deps.stamp: $(REQUIREMENTS) pyproject.toml | $(VENV_DIR)/bin/python
	$(call log_step,"Installing dependencies")
	@if [[ "$(PIP_UPGRADE)" == "1" ]]; then $(PIP) install --upgrade pip; fi
	@$(PIP) install -r $(REQUIREMENTS)
	@$(PIP) install -e .
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
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m pytest $(PYTEST_COMMON) $(PYTEST_LIVE_TARGETS)
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
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m pytest $(PYTEST_COMMON) \
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

broker-reap: runtime-layout ## Reap stale broker-owned pidfiles, sockets, and orphaned process groups
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.runtime_reaper --runtime-root "$(RUNTIME_ROOT)"

broker-smoke: runtime-layout ## Run broker wiring safety smoke without writing client configs
	@$(MAKE) --no-print-directory config-render CLIENT=codex CONFIG_RENDER_APPLY=0 RUNTIME_ROOT="$(RUNTIME_ROOT)" SOCKET_PATH="$(SOCKET_PATH)"
	@$(MAKE) --no-print-directory config-render CLIENT=claude CONFIG_RENDER_APPLY=0 RUNTIME_ROOT="$(RUNTIME_ROOT)" SOCKET_PATH="$(SOCKET_PATH)"
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
		--call-args '$(FACADE_CALL_ARGS)'

codex-facade-smoke: PROFILE=codex
codex-facade-smoke: facade-smoke ## Exercise compact Codex broker facade through the client shim

claude-facade-smoke: PROFILE=claude
claude-facade-smoke: facade-smoke ## Exercise compact Claude broker facade through the client shim without wiring Claude

gemini-facade-smoke: PROFILE=gemini
gemini-facade-smoke: facade-smoke ## Exercise compact Gemini broker facade profile without rendering a Gemini client

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
codex-deferred-acceptance: runtime-layout ## Print maintainer-only Codex deferred-tool acceptance steps
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

release-smoke: ## Run clean-tree public setup smoke from tracked files
	@"$(ROOT)/scripts/release-smoke.sh"

public-export: ## Copy public-safe files to PUBLIC_REPO after allowlist, denylist, marker, and secret scans
	@test -n "$(PUBLIC_REPO)" || { $(call log_error,"Set PUBLIC_REPO"); exit 1; }
	@if [[ "$(PUBLIC_EXPORT_DELETE_STALE)" == "1" ]]; then \
		DELETE_ARGS=(); \
	else \
		DELETE_ARGS=(--no-delete-stale); \
	fi; \
	$(PYTHON_BIN) "$(ROOT)/scripts/public-export.py" \
		--repo-root "$(ROOT)" \
		--public-repo "$(PUBLIC_REPO)" \
		--allowlist "$(PUBLIC_EXPORT_ALLOWLIST)" \
		--denylist "$(PUBLIC_EXPORT_DENYLIST)" \
		"$${DELETE_ARGS[@]}"

public-export-check: public-export ## Validate exported public checkout skeleton
	@test -f "$(PUBLIC_REPO)/README.md"
	@test -f "$(PUBLIC_REPO)/LICENSE"
	@test -f "$(PUBLIC_REPO)/SECURITY.md"
	@test -f "$(PUBLIC_REPO)/CONTRIBUTING.md"
	@test -f "$(PUBLIC_REPO)/CHANGELOG.md"
	@test -f "$(PUBLIC_REPO)/ROADMAP.md"
	@test -f "$(PUBLIC_REPO)/.github/ISSUE_TEMPLATE/bug_report.md"
	@test -f "$(PUBLIC_REPO)/src/mcp_broker/broker.py"
	@test ! -e "$(PUBLIC_REPO)/AGENTS.md"
	@test ! -e "$(PUBLIC_REPO)/CLAUDE.md"
	@test ! -e "$(PUBLIC_REPO)/TODO.md"
	@test ! -e "$(PUBLIC_REPO)/docs/plans"
	@test ! -e "$(PUBLIC_REPO)/docs/current-mcp-inventory.md"
	$(call log_success,"public-export-check passed")

public-release-dry-run: ## Export to a clean public tree and run setup, validation, smoke, and public tests
	@"$(ROOT)/scripts/public-release-dry-run.sh"

require-maintainer-tools:
	@test -x "$(CHECK_VIOLATIONS)" || { $(call log_error,"Missing maintainer tool: CHECK_VIOLATIONS=$(CHECK_VIOLATIONS)"); exit 2; }
	@test -x "$(GRADE_QUALITY)" || { $(call log_error,"Missing maintainer tool: GRADE_QUALITY=$(GRADE_QUALITY)"); exit 2; }
	@test -x "$(GIT_SECURITY_GUARD)" || { $(call log_error,"Missing maintainer tool: GIT_SECURITY_GUARD=$(GIT_SECURITY_GUARD)"); exit 2; }

violations: maintainer-violations

grade-quality: maintainer-grade-quality

maintainer-violations: require-maintainer-tools
	@mkdir -p "$(QUALITY_DIR)"
	@"$(CHECK_VIOLATIONS)" \
		--repo-root "$(ROOT)" \
		--log --log-file "$(VIOLATIONS_LOG)" \
		--json --json-file "$(VIOLATIONS_JSON)"

maintainer-grade-quality: require-maintainer-tools maintainer-violations
	@mkdir -p "$(QUALITY_DIR)"
	@"$(GRADE_QUALITY)" \
		--no-refresh \
		--violations-json "$(VIOLATIONS_JSON)" \
		--output-json "$(GRADE_REPORT_JSON)" \
		"$(ROOT)"
	@$(PYTHON) "$(ROOT)/scripts/enforce_grade_quality.py" "$(GRADE_REPORT_JSON)"

precommit: test-unit test-journey ## Public commit gate using repo-local checks
	$(call log_success,"Precommit gate passed")

maintainer-precommit: require-maintainer-tools
	@if git -C "$(ROOT)" remote get-url origin >/dev/null 2>&1; then \
		"$(GIT_SECURITY_GUARD)" --repo-root "$(ROOT)" --list-alerts --check-gitguardian; \
	else \
		printf "\033[1;33m[WARN]\033[0m origin remote not configured yet - GitHub/GitGuardian remote checks deferred until repo creation\n"; \
	fi
	@$(MAKE) --no-print-directory test-unit
	@$(MAKE) --no-print-directory test-journey
	@$(MAKE) --no-print-directory maintainer-violations

quality-gate: test-cov ## Public quality gate using repo-local tests and coverage
	$(call log_success,"Quality gate passed")

maintainer-quality-gate: test-cov maintainer-violations maintainer-grade-quality
	$(call log_success,"Maintainer quality gate passed")

clean: ## Remove generated artifacts
	@rm -rf "$(ROOT)/var/coverage" "$(ROOT)/var/test-logs" "$(ROOT)/var/quality" "$(ROOT)/.pytest_cache" "$(ROOT)/htmlcov"
	@rm -f "$(ROOT)/violations.json" "$(ROOT)/violations.log" "$(ROOT)/grade_quality_report.json"
	$(call log_success,"Clean complete")
