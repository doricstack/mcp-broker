.PHONY: setup venv deps clean

setup: config-init venv deps doctor ## Create config, venv, deps, and verify runtime layout
	$(call log_success,"Setup complete")

venv: $(VENV_DIR)/bin/python ## Create project venv

$(VENV_DIR)/bin/python:
	$(call log_step,"Creating venv $(VENV_DIR)")
	@$(PYTHON_BIN) -m venv $(VENV_DIR)
	$(call log_success,"Venv ready")

deps: $(VENV_DIR)/.deps.stamp ## Install Python dependencies
	$(call log_success,"Dependencies ready")

$(VENV_DIR)/.deps.stamp: $(VENV_DIR)/bin/python $(REQUIREMENTS) pyproject.toml $(CONFIG_TEMPLATE_PATH)
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

bundle-validate: ## Validate BUNDLE without changing runtime state
	@test -n "$(BUNDLE)" || { $(call log_error,"BUNDLE is required"); exit 2; }
	@test -f "$(BUNDLE)" || { $(call log_error,"Missing BUNDLE=$(BUNDLE)"); exit 1; }
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.cli bundle validate --bundle "$(BUNDLE)"
	$(call log_success,"Bundle validation passed")

clean: ## Remove generated artifacts
	@rm -rf "$(ROOT)/var/coverage" "$(ROOT)/var/test-logs" "$(ROOT)/var/quality" "$(ROOT)/.pytest_cache" "$(ROOT)/.mutmut-cache" "$(ROOT)/mutants" "$(ROOT)/htmlcov" "$(ROOT)/dist" "$(ROOT)/build"
	@rm -f "$(ROOT)/violations.json" "$(ROOT)/violations.log" "$(ROOT)/grade_quality_report.json"
	$(call log_success,"Clean complete")
