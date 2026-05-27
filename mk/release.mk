.PHONY: mutation _mutation-impl mutation-linux _mutation-linux-impl release-gate _release-gate-impl _release-gate-quality _release-gate-package _release-gate-smoke _release-gate-mutation

mutation: $(VENV_DIR)/.deps.stamp ## Run mutation tests with mutmut
	$(call timed_make,"mutation: total",_mutation-impl)

_mutation-impl:
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
	$(call timed_make,"mutation-linux: total",_mutation-linux-impl)

_mutation-linux-impl:
	@MCP_BROKER_MUTATION_IMAGE="$(MUTATION_IMAGE)" \
		MCP_BROKER_MUTATION_MAX_CHILDREN="$(MUTATION_MAX_CHILDREN)" \
		MCP_BROKER_MUTATION_ARGS="$(MUTATION_ARGS)" \
		MCP_BROKER_MUTATION_LOG="$(MUTATION_LOG)" \
		MCP_BROKER_MUTATION_MUTANTS_DIR="$(MUTATION_MUTANTS_DIR)" \
		"$(ROOT)/scripts/linux-mutation.sh"

release-gate: ## Run release gates with mutation parallelized with non-mutating checks
	$(call timed_make,"release-gate: total",_release-gate-impl)

_release-gate-impl:
	$(call timed_make,"release-gate: deps",deps)
	$(call timed_make,"release-gate: parallel children",-j $(RELEASE_GATE_JOBS) _release-gate-quality _release-gate-package _release-gate-smoke _release-gate-mutation)
	$(call log_success,"Release gate passed")

_release-gate-quality:
	@mkdir -p "$(RELEASE_GATE_LOG_DIR)"
	$(call timed_make,"release-gate child: quality-gate",PYTEST_WORKERS="$(PYTEST_RELEASE_WORKERS)" quality-gate,"$(RELEASE_GATE_LOG_DIR)/quality-gate.log")

_release-gate-package:
	@mkdir -p "$(RELEASE_GATE_LOG_DIR)"
	$(call timed_make,"release-gate child: package-check",package-check,"$(RELEASE_GATE_LOG_DIR)/package-check.log")

_release-gate-smoke:
	@mkdir -p "$(RELEASE_GATE_LOG_DIR)"
	$(call timed_make,"release-gate child: release-smoke",release-smoke,"$(RELEASE_GATE_LOG_DIR)/release-smoke.log")

_release-gate-mutation:
	@mkdir -p "$(RELEASE_GATE_LOG_DIR)"
	$(call timed_make,"release-gate child: $(RELEASE_MUTATION_TARGET)",$(RELEASE_MUTATION_TARGET),"$(RELEASE_GATE_LOG_DIR)/$(RELEASE_MUTATION_TARGET).log")
