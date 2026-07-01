.PHONY: plugin-install plugin-status plugin-render plugin-apply plugin-rollback plugin-bootstrap-preflight plugin-bootstrap-plan plugin-bootstrap-apply plugin-bootstrap-status plugin-bootstrap-rollback plugin-bootstrap-uninstall

plugin-install: ## Prepare local broker runtime for plugin use without writing client configs
	@$(MAKE) --no-print-directory setup

plugin-status: ## Query broker status for the plugin workflow
	@$(MAKE) --no-print-directory broker-status \
		RUNTIME_ROOT="$(RUNTIME_ROOT)" \
		SOCKET_PATH="$(SOCKET_PATH)"

plugin-render: ## Dry-run client config rendering for PLUGIN_CLIENT
	@$(MAKE) --no-print-directory config-render \
		CLIENT="$(PLUGIN_CLIENT)" \
		CONFIG_RENDER_APPLY=0 \
		RUNTIME_ROOT="$(RUNTIME_ROOT)" \
		SOCKET_PATH="$(SOCKET_PATH)"

plugin-apply: ## Render client config; writes only when PLUGIN_APPLY=1
	@if [[ "$(PLUGIN_APPLY)" == "1" ]]; then \
		APPLY_VALUE=1; \
	else \
		APPLY_VALUE=0; \
	fi; \
	$(MAKE) --no-print-directory config-render \
		CLIENT="$(PLUGIN_CLIENT)" \
		CONFIG_RENDER_APPLY=$$APPLY_VALUE \
		RUNTIME_ROOT="$(RUNTIME_ROOT)" \
		SOCKET_PATH="$(SOCKET_PATH)"

plugin-rollback: ## Restore latest client config backup only when PLUGIN_APPLY=1
	@[[ "$(PLUGIN_APPLY)" == "1" ]] || { printf "\033[1;31m[ERROR]\033[0m %s\n" "PLUGIN_APPLY=1 is required for plugin rollback" >&2; exit 2; }
	@$(MAKE) --no-print-directory config-rollback \
		CLIENT="$(PLUGIN_CLIENT)" \
		RUNTIME_ROOT="$(RUNTIME_ROOT)" \
		SOCKET_PATH="$(SOCKET_PATH)"

plugin-bootstrap-preflight: runtime-layout ## Verify runtime package metadata without writing bootstrap state
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.cli runtime bootstrap preflight \
		--metadata "$(BOOTSTRAP_METADATA)" \
		--state-dir "$(STATE_DIR)"

plugin-bootstrap-plan: runtime-layout ## Print the runtime bootstrap activation plan
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.cli runtime bootstrap plan \
		--metadata "$(BOOTSTRAP_METADATA)" \
		--state-dir "$(STATE_DIR)"

plugin-bootstrap-apply: runtime-layout ## Apply runtime bootstrap only when BOOTSTRAP_APPROVED=1
	@[[ "$(BOOTSTRAP_APPROVED)" == "1" ]] || { printf "\033[1;31m[ERROR]\033[0m %s\n" "BOOTSTRAP_APPROVED=1 is required for bootstrap apply" >&2; exit 2; }
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.cli runtime bootstrap apply \
		--metadata "$(BOOTSTRAP_METADATA)" \
		--state-dir "$(STATE_DIR)" \
		--approved

plugin-bootstrap-status: runtime-layout ## Print latest runtime bootstrap transaction status
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.cli runtime bootstrap status \
		--state-dir "$(STATE_DIR)"

plugin-bootstrap-rollback: runtime-layout ## Roll back runtime bootstrap only when BOOTSTRAP_APPROVED=1
	@[[ "$(BOOTSTRAP_APPROVED)" == "1" ]] || { printf "\033[1;31m[ERROR]\033[0m %s\n" "BOOTSTRAP_APPROVED=1 is required for bootstrap rollback" >&2; exit 2; }
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.cli runtime bootstrap rollback \
		--state-dir "$(STATE_DIR)" \
		--approved

plugin-bootstrap-uninstall: runtime-layout ## Uninstall active runtime only when BOOTSTRAP_APPROVED=1
	@[[ "$(BOOTSTRAP_APPROVED)" == "1" ]] || { printf "\033[1;31m[ERROR]\033[0m %s\n" "BOOTSTRAP_APPROVED=1 is required for bootstrap uninstall" >&2; exit 2; }
	@PYTHONPATH="$(PYTHONPATH)" $(PYTHON) -m mcp_broker.cli runtime bootstrap uninstall \
		--state-dir "$(STATE_DIR)" \
		--approved
