.PHONY: plugin-install plugin-status plugin-render plugin-apply plugin-rollback

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
	@[[ "$(PLUGIN_APPLY)" == "1" ]] || { $(call log_error,"PLUGIN_APPLY=1 is required for plugin rollback"); exit 2; }
	@$(MAKE) --no-print-directory config-rollback \
		CLIENT="$(PLUGIN_CLIENT)" \
		RUNTIME_ROOT="$(RUNTIME_ROOT)" \
		SOCKET_PATH="$(SOCKET_PATH)"
