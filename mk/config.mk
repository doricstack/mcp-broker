.PHONY: config-init config-validate

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
CPU_COUNT ?= $(shell "$(PYTHON_BIN)" -c 'import os, sys; sys.stdout.write(str(os.cpu_count() or 4))' 2>/dev/null || printf 4)
LOCAL_CPU_BUDGET ?= 4
RELEASE_MUTATION_TARGET ?= $(if $(filter Darwin,$(UNAME_S)),mutation-linux,mutation)

PYTEST_MAXFAIL    ?= 1
PYTEST_TIMEOUT    ?= 30
PYTEST_LIVE_TIMEOUT ?= 120
PYTEST_COV_TIMEOUT ?= $(PYTEST_LIVE_TIMEOUT)
PYTEST_ARGS       ?=
PYTEST_WORKERS ?= $(LOCAL_CPU_BUDGET)
PYTEST_TARGETED_WORKERS ?= 0
PYTEST_FANOUT_WORKERS ?= $(shell "$(PYTHON_BIN)" -c 'import sys; sys.stdout.write(str(max(1, int("$(LOCAL_CPU_BUDGET)") // int("$(TEST_JOBS)"))))' 2>/dev/null || printf 1)
PYTEST_PRECOMMIT_WORKERS ?= $(shell "$(PYTHON_BIN)" -c 'import sys; sys.stdout.write(str(max(1, int("$(LOCAL_CPU_BUDGET)") // int("$(PRECOMMIT_JOBS)"))))' 2>/dev/null || printf 1)
PYTEST_RELEASE_WORKERS ?= $(shell "$(PYTHON_BIN)" -c 'import sys; sys.stdout.write(str(max(1, int("$(LOCAL_CPU_BUDGET)") // int("$(RELEASE_GATE_JOBS)"))))' 2>/dev/null || printf 1)
PYTEST_XDIST_DIST ?= loadfile
PYTEST_XDIST_ARGS ?= $(if $(filter 0,$(PYTEST_WORKERS)),,-n $(PYTEST_WORKERS) --dist $(PYTEST_XDIST_DIST))
PYTEST_TARGETED_XDIST_ARGS ?= $(if $(filter 0,$(PYTEST_TARGETED_WORKERS)),,-n $(PYTEST_TARGETED_WORKERS) --dist $(PYTEST_XDIST_DIST))
TEST_JOBS ?= 4
PRECOMMIT_JOBS ?= 2
RELEASE_GATE_JOBS ?= 2
PUBLISH_CHECK_JOBS ?= 2
PUBLISH_EVERYWHERE_JOBS ?= 3
XDIST_BENCHMARK_TARGETS ?= $(PY_UNIT_DIR) $(PY_JOURNEY_DIR)
TEST_RUNTIME_ROOT ?= $(ROOT)/var/test-runtime
COV_FAIL_UNDER    ?= 100
COV_SRC           ?= src/mcp_broker
COV_DIR           ?= $(ROOT)/var/coverage
COV_FILE          ?= $(COV_DIR)/.coverage
TEST_LOG_DIR      ?= $(ROOT)/var/test-logs
QUALITY_DIR       ?= $(ROOT)/var/quality
RELEASE_GATE_LOG_DIR ?= $(QUALITY_DIR)/release-gate
GENERATED_SCAN_EXCLUDE_PATHS ?= \
	$(ROOT)/.mutmut-cache \
	$(ROOT)/mutants \
	$(ROOT)/var/public-*check \
	$(ROOT)/var/public-export-check \
	$(QUALITY_DIR)/mutants-* \
	$(QUALITY_DIR)/mutation-linux*.log
VIOLATIONS_JSON   ?= $(QUALITY_DIR)/violations.json
VIOLATIONS_LOG    ?= $(QUALITY_DIR)/violations.log
VIOLATIONS_JOBS   ?= $(LOCAL_CPU_BUDGET)
GRADE_REPORT_JSON ?= $(QUALITY_DIR)/grade_quality_report.json
PACKAGE_DIST_DIR  ?= $(ROOT)/dist
UV                ?= uv
UVX               ?= uvx
NPM               ?= npm
NPX               ?= npx
NPM_DIR           ?= $(ROOT)/npm
NPM_PACKAGE_NAME  ?= @navinagrawal/mcp-broker
PACKAGE_INSTALL_VERSION ?= 1.0.0
DOCKER_IMAGE      ?= mcp-broker:local
DOCKER_PLATFORM   ?=
DOCKER_PLATFORMS  ?= linux/amd64,linux/arm64
DOCKER_PUSH       ?= 0
DOCKER_SBOM       ?= true
DOCKER_PROVENANCE ?= true
DOCKER_SOURCE_URL ?= https://github.com/NavinAgrawal/mcp-broker
PACKAGE_VERSION   ?= $(shell PYTHONPATH="$(ROOT)/src" "$(PYTHON_BIN)" -c 'import mcp_broker, sys; sys.stdout.write(mcp_broker.__version__)')
PACKAGE_MINOR_VERSION ?= $(shell PYTHONPATH="$(ROOT)/src" "$(PYTHON_BIN)" -c 'import mcp_broker, sys; parts=mcp_broker.__version__.split("."); sys.stdout.write(".".join(parts[:2]))')
DOCKER_LOCAL_PLATFORM ?= $(if $(filter Darwin,$(UNAME_S)),linux/arm64,linux/amd64)
DOCKER_REGISTRY ?= docker.io
DOCKER_NAMESPACE ?= navinagrawal
DOCKER_IMAGE_NAME ?= mcp-broker
DOCKER_RELEASE_TAG ?= $(PACKAGE_VERSION)
DOCKER_RELEASE_IMAGE ?= $(DOCKER_REGISTRY)/$(DOCKER_NAMESPACE)/$(DOCKER_IMAGE_NAME):$(DOCKER_RELEASE_TAG)
DOCKER_MINOR_IMAGE ?= $(DOCKER_REGISTRY)/$(DOCKER_NAMESPACE)/$(DOCKER_IMAGE_NAME):$(PACKAGE_MINOR_VERSION)
GHCR_IMAGE ?= ghcr.io/$(DOCKER_NAMESPACE)/$(DOCKER_IMAGE_NAME):$(DOCKER_RELEASE_TAG)
GHCR_MINOR_IMAGE ?= ghcr.io/$(DOCKER_NAMESPACE)/$(DOCKER_IMAGE_NAME):$(PACKAGE_MINOR_VERSION)
DOCKER_PUBLISH_IMAGES ?= $(DOCKER_RELEASE_IMAGE) $(DOCKER_MINOR_IMAGE) $(GHCR_IMAGE) $(GHCR_MINOR_IMAGE)
DOCKER_MCP_CATALOG_FILE ?= $(ROOT)/docker/mcp-catalog/mcp-broker.yaml
DOCKER_MCP_CATALOG_REF ?= mcp-broker-local-catalog:local
MCP_REGISTRY_NAME ?= io.github.NavinAgrawal/mcp-broker
MCP_REGISTRY_SEARCH_URL ?= https://registry.modelcontextprotocol.io/v0.1/servers?search=$(MCP_REGISTRY_NAME)
PUBLISH_EVERYWHERE_APPLY ?= 0
EXPECTED_PUBLISH_VERSION ?=
MCPB_MANIFEST     ?= $(ROOT)/mcpb/manifest.json
PYTEST_COMMON     ?= --color=yes --force-sugar --maxfail=$(PYTEST_MAXFAIL) --timeout=$(PYTEST_TIMEOUT) $(PYTEST_XDIST_ARGS)
PYTEST_TARGETED_COMMON ?= --color=yes --force-sugar --maxfail=$(PYTEST_MAXFAIL) --timeout=$(PYTEST_TIMEOUT) $(PYTEST_TARGETED_XDIST_ARGS)
PYTEST_LIVE_COMMON ?= --color=yes --force-sugar --maxfail=$(PYTEST_MAXFAIL) --timeout=$(PYTEST_LIVE_TIMEOUT) $(PYTEST_XDIST_ARGS)
PYTEST_COV_COMMON ?= --color=yes --force-sugar --maxfail=$(PYTEST_MAXFAIL) --timeout=$(PYTEST_COV_TIMEOUT) $(PYTEST_XDIST_ARGS)
BROKER_WAIT_SECONDS ?= 10
MUTATION_MAX_CHILDREN ?= $(LOCAL_CPU_BUDGET)
MUTATION_ARGS    ?=
MUTATION_IMAGE   ?= python:3.11-bookworm
MUTATION_STATS_JSON ?= $(QUALITY_DIR)/mutation_stats.json
MUTATION_LOG ?= $(QUALITY_DIR)/mutation-linux.log
MUTATION_MUTANTS_DIR ?= $(QUALITY_DIR)/mutants-linux
MUTATION_MIN_SCORE ?= 100
MUTATION_FAIL_STATUSES ?= survived no_tests skipped suspicious timeout check_was_interrupted_by_user segfault not_checked
SHARED_SCRIPTS_DIR ?= $(HOME)/.llm-shared/scripts
CHECK_VIOLATIONS ?= $(SHARED_SCRIPTS_DIR)/check-violations.sh
GRADE_QUALITY    ?= $(SHARED_SCRIPTS_DIR)/grade_quality.sh

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
