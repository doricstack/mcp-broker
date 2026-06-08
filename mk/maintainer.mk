.PHONY: require-violations-tool require-grade-quality-tool violations grade-quality maintainer-violations maintainer-grade-quality

require-violations-tool:
	@test -x "$(CHECK_VIOLATIONS)" || { $(call log_error,"Missing maintainer tool: CHECK_VIOLATIONS=$(CHECK_VIOLATIONS)"); exit 2; }

require-grade-quality-tool: require-violations-tool
	@test -x "$(GRADE_QUALITY)" || { $(call log_error,"Missing maintainer tool: GRADE_QUALITY=$(GRADE_QUALITY)"); exit 2; }

violations: maintainer-violations

grade-quality: maintainer-grade-quality

maintainer-violations: require-violations-tool
	@mkdir -p "$(QUALITY_DIR)"
	@for generated_path in $(GENERATED_SCAN_EXCLUDE_PATHS); do rm -rf $$generated_path; done
	@"$(CHECK_VIOLATIONS)" \
		--repo-root "$(ROOT)" \
		--jobs "$(VIOLATIONS_JOBS)" \
		$(VIOLATIONS_FLAGS) \
		--log --log-file "$(VIOLATIONS_LOG)" \
		--json --json-file "$(VIOLATIONS_JSON)"

maintainer-grade-quality: require-grade-quality-tool maintainer-violations
	@mkdir -p "$(QUALITY_DIR)"
	@"$(GRADE_QUALITY)" \
		--no-refresh \
		--violations-json "$(VIOLATIONS_JSON)" \
		--output-json "$(GRADE_REPORT_JSON)" \
		"$(ROOT)"
	@$(PYTHON) "$(ROOT)/scripts/enforce_grade_quality.py" "$(GRADE_REPORT_JSON)"
