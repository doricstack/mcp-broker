.PHONY: release-smoke package-build package-check package-install-smoke public-stable-surface-smoke public-release-surface-smoke npm-account-check npm-package-check npm-smoke npm-release-smoke docker-build docker-smoke docker-buildx docker-mcp-catalog-smoke docker-publish-check docker-release-smoke mcpb-validate publish-version-check publish-everywhere-check _publish-everywhere-check-impl publish-everywhere _publish-everywhere-impl _publish-check-docker-smoke _publish-check-docker-buildx _publish-everywhere-pypi _publish-everywhere-npm _publish-everywhere-docker _publish-everywhere-mcp-registry

release-smoke: ## Run clean-tree public setup smoke from tracked files
	@"$(ROOT)/scripts/release-smoke.sh"

package-build: $(VENV_DIR)/.deps.stamp ## Build wheel and source distribution into dist/
	@rm -rf "$(PACKAGE_DIST_DIR)"
	@$(PYTHON) -m build --outdir "$(PACKAGE_DIST_DIR)" "$(ROOT)"
	$(call log_success,"Package artifacts built in $(PACKAGE_DIST_DIR)")

package-check: package-build ## Validate built package metadata
	@$(PYTHON) -m twine check "$(PACKAGE_DIST_DIR)"/*
	$(call log_success,"Package artifacts passed twine check")

package-install-smoke: ## Validate pipx and uvx against the published stable PyPI package
	@command -v pipx >/dev/null 2>&1 || { printf "\033[1;31m[ERROR]\033[0m pipx is required for package-install-smoke\n" >&2; exit 2; }
	@command -v "$(UVX)" >/dev/null 2>&1 || { printf "\033[1;31m[ERROR]\033[0m uvx is required for package-install-smoke\n" >&2; exit 2; }
	@tmpdir="$$(mktemp -d)"; \
		trap 'rm -rf "$$tmpdir"' EXIT; \
		PIPX_HOME="$$tmpdir/pipx-home" PIPX_BIN_DIR="$$tmpdir/pipx-bin" \
			pipx run --spec "mcp-broker==$(PACKAGE_INSTALL_VERSION)" mcp-broker --help >/dev/null; \
		UV_TOOL_DIR="$$tmpdir/uv-tools" UV_CACHE_DIR="$$tmpdir/uv-cache" \
			"$(UVX)" --from "mcp-broker==$(PACKAGE_INSTALL_VERSION)" mcp-broker --help >/dev/null
	$(call log_success,"pipx and uvx install smoke passed: mcp-broker $(PACKAGE_INSTALL_VERSION)")

public-stable-surface-smoke: ## Download and verify public stable artifacts from real registries
	@PUBLIC_SURFACE_VERSION="$(PACKAGE_INSTALL_VERSION)" \
		PUBLIC_SURFACE_REQUIRE_NPM=0 \
		PUBLIC_SURFACE_REQUIRE_DOCKER=0 \
		"$(ROOT)/scripts/public-surface-smoke.sh"

public-release-surface-smoke: ## Download and verify every public release surface after 1.1.0 publication
	@PUBLIC_SURFACE_VERSION="$(PACKAGE_VERSION)" \
		PUBLIC_SURFACE_REQUIRE_NPM=1 \
		PUBLIC_SURFACE_REQUIRE_DOCKER=1 \
		NPM_PACKAGE_NAME="$(NPM_PACKAGE_NAME)" \
		DOCKER_RELEASE_IMAGE="$(DOCKER_RELEASE_IMAGE)" \
		"$(ROOT)/scripts/public-surface-smoke.sh"

npm-account-check: ## Verify the maintainer NPM login and scoped package visibility
	@test -d "$(NPM_DIR)" || { printf "\033[1;31m[ERROR]\033[0m Missing NPM package directory: %s\n" "$(NPM_DIR)" >&2; exit 1; }
	@cd "$(NPM_DIR)" && $(NPM) whoami
	@cd "$(NPM_DIR)" && $(NPM) view "$(NPM_PACKAGE_NAME)" --json || true

npm-package-check: ## Validate the scoped NPM package tarball contents
	@test -d "$(NPM_DIR)" || { printf "\033[1;31m[ERROR]\033[0m Missing NPM package directory: %s\n" "$(NPM_DIR)" >&2; exit 1; }
	@cd "$(NPM_DIR)" && $(NPM) pack --dry-run --json
	$(call log_success,"NPM package dry run passed: $(NPM_PACKAGE_NAME)")

npm-smoke: ## Run the local NPM bridge wrapper
	@test -d "$(NPM_DIR)" || { printf "\033[1;31m[ERROR]\033[0m Missing NPM package directory: %s\n" "$(NPM_DIR)" >&2; exit 1; }
	@cd "$(NPM_DIR)" && MCP_BROKER_NPM_DEV_ROOT="$(ROOT)" node bin/mcp-broker.js --help
	$(call log_success,"NPM smoke passed: $(NPM_PACKAGE_NAME)")

npm-release-smoke: ## Verify the published NPM bridge package
	@$(NPM) view "$(NPM_PACKAGE_NAME)" version repository dist-tags --json
	@$(NPX) -y "$(NPM_PACKAGE_NAME)" --help
	$(call log_success,"NPM release smoke passed: $(NPM_PACKAGE_NAME)")

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
		SBOM_ARG="$(DOCKER_SBOM)"; \
		PROVENANCE_ARG="$(DOCKER_PROVENANCE)"; \
	else \
		OUTPUT_ARG="--load"; \
		SBOM_ARG="false"; \
		PROVENANCE_ARG="false"; \
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
		--sbom=$$SBOM_ARG \
		--provenance=$$PROVENANCE_ARG \
		-t "$(DOCKER_IMAGE)" \
		$$OUTPUT_ARG \
		"$(ROOT)"
	$(call log_success,"Docker buildx completed: $(DOCKER_IMAGE)")

docker-mcp-catalog-smoke: ## Verify Docker MCP Toolkit can create a custom catalog from file metadata
	@test -f "$(DOCKER_MCP_CATALOG_FILE)" || { printf "\033[1;31m[ERROR]\033[0m Missing Docker MCP catalog file: %s\n" "$(DOCKER_MCP_CATALOG_FILE)" >&2; exit 2; }
	@docker mcp catalog remove "$(DOCKER_MCP_CATALOG_REF)" >/dev/null 2>&1 || true
	@docker mcp catalog create "$(DOCKER_MCP_CATALOG_REF)" \
		--title "mcp-broker local" \
		--server "file://$(DOCKER_MCP_CATALOG_FILE)" >/dev/null
	@trap 'docker mcp catalog remove "$(DOCKER_MCP_CATALOG_REF)" >/dev/null 2>&1 || true' EXIT; \
		docker mcp catalog server ls "$(DOCKER_MCP_CATALOG_REF)" --format json | grep -q '"mcp-broker"'
	$(call log_success,"Docker MCP custom catalog smoke passed: $(DOCKER_MCP_CATALOG_REF)")

docker-publish-check: ## Verify published Docker manifests
	@for image in $(DOCKER_PUBLISH_IMAGES); do \
		docker buildx imagetools inspect "$$image" >/dev/null; \
		printf "\033[1;32m[OK]\033[0m Docker manifest exists: %s\n" "$$image"; \
	done

docker-release-smoke: ## Smoke test the published Docker image
	$(call log_step,"Smoke testing published Docker image $(DOCKER_RELEASE_IMAGE)")
	@printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"docker-release-smoke","version":"0"}}}\n{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n' | docker run --rm -i "$(DOCKER_RELEASE_IMAGE)" | grep -q '"tools"'
	$(call log_success,"Docker release smoke passed: $(DOCKER_RELEASE_IMAGE)")

mcpb-validate: ## Validate MCPB manifest metadata
	$(call log_step,"Validating MCPB manifest")
	@npx -y @anthropic-ai/mcpb validate "$(MCPB_MANIFEST)"
	$(call log_success,"MCPB manifest passed")

publish-version-check: ## Verify all release metadata versions match
	@EXPECTED_PUBLISH_VERSION="$(EXPECTED_PUBLISH_VERSION)" GITHUB_REF_NAME="$${GITHUB_REF_NAME:-}" $(PYTHON) "$(ROOT)/scripts/check_release_versions.py"
	$(call log_success,"Release versions are aligned")

publish-everywhere-check: ## Run all local gates required before registry publication
	$(call timed_make,"publish-everywhere-check: total",_publish-everywhere-check-impl)

_publish-everywhere-check-impl:
	$(call timed_make,"publish-everywhere-check: version check",publish-version-check)
	$(call timed_make,"publish-everywhere-check: release gate",release-gate)
	$(call timed_make,"publish-everywhere-check: package smoke children",-j $(PUBLISH_CHECK_JOBS) npm-package-check npm-smoke _publish-check-docker-smoke _publish-check-docker-buildx)
	$(call log_success,"Publish-everywhere checks passed")

_publish-check-docker-smoke:
	$(call timed_make,"publish check child: docker-smoke",docker-smoke DOCKER_IMAGE="mcp-broker:publish-check")

_publish-check-docker-buildx:
	$(call timed_make,"publish check child: docker-buildx",docker-buildx DOCKER_IMAGE="mcp-broker:buildx-check" DOCKER_PLATFORMS="$(DOCKER_LOCAL_PLATFORM)")

publish-everywhere: ## CI-only one-shot publication to PyPI, NPM, Docker Hub, GHCR, and MCP Registry
	$(call timed_make,"publish-everywhere: total",_publish-everywhere-impl)

_publish-everywhere-impl:
	@test "$(GITHUB_ACTIONS)" = "true" || { printf "\033[1;31m[ERROR]\033[0m publish-everywhere must run in GitHub Actions\n" >&2; exit 2; }
	@test "$(PUBLISH_EVERYWHERE_APPLY)" = "1" || { printf "\033[1;31m[ERROR]\033[0m Set PUBLISH_EVERYWHERE_APPLY=1 to publish\n" >&2; exit 2; }
	$(call timed_make,"publish-everywhere: preflight checks",publish-everywhere-check)
	$(call timed_make,"publish-everywhere: pypi",_publish-everywhere-pypi)
	$(call timed_make,"publish-everywhere: parallel registries",-j $(PUBLISH_EVERYWHERE_JOBS) _publish-everywhere-npm _publish-everywhere-docker _publish-everywhere-mcp-registry)
	$(call log_success,"Publish-everywhere completed")

_publish-everywhere-pypi:
	@status="$$(curl -fsS -o /dev/null -w '%{http_code}' "$(PYPI_VERSION_URL)" || true)"; \
	if [ "$$status" = "200" ]; then \
		printf "\033[1;32m[OK]\033[0m PyPI package already exists: %s==%s\n" "$(PYPI_PROJECT_NAME)" "$(PACKAGE_VERSION)"; \
	elif [ "$$status" = "404" ]; then \
		command -v "$(UV)" >/dev/null 2>&1 || { printf "\033[1;31m[ERROR]\033[0m uv is required for publish-everywhere\n" >&2; exit 2; }; \
		"$(UV)" publish --trusted-publishing always --check-url "https://pypi.org/simple/mcp-broker/" "$(PACKAGE_DIST_DIR)"/*; \
	else \
		printf "\033[1;31m[ERROR]\033[0m PyPI version check failed for %s (HTTP %s)\n" "$(PYPI_VERSION_URL)" "$$status" >&2; \
		exit 2; \
	fi
	$(call log_success,"PyPI publish target completed: $(PACKAGE_VERSION)")

_publish-everywhere-npm:
	@if $(NPM) view "$(NPM_PACKAGE_NAME)@$(PACKAGE_VERSION)" version >/dev/null 2>&1; then \
		printf "\033[1;32m[OK]\033[0m NPM package already exists: %s@%s\n" "$(NPM_PACKAGE_NAME)" "$(PACKAGE_VERSION)"; \
	else \
		cd "$(NPM_DIR)" && $(NPM) publish --access public --provenance; \
	fi
	$(call log_success,"NPM publish target completed: $(NPM_PACKAGE_NAME)")

_publish-everywhere-docker:
	@TAG_ARGS=(); \
	for image in $(DOCKER_PUBLISH_IMAGES); do TAG_ARGS+=("-t" "$$image"); done; \
	docker buildx build \
		--platform "$(DOCKER_PLATFORMS)" \
		--build-arg VERSION="$(PACKAGE_VERSION)" \
		--build-arg VCS_REF="$$(git -C "$(ROOT)" rev-parse --short HEAD 2>/dev/null || printf unknown)" \
		--build-arg SOURCE_URL="$(DOCKER_SOURCE_URL)" \
		--sbom=$(DOCKER_SBOM) \
		--provenance=$(DOCKER_PROVENANCE) \
		"$${TAG_ARGS[@]}" \
		--push \
		"$(ROOT)"
	$(call log_success,"Published Docker images: $(DOCKER_PUBLISH_IMAGES)")
	$(call timed_make,"publish child: docker-publish-check",docker-publish-check)

_publish-everywhere-mcp-registry:
	@if curl -fsS "$(MCP_REGISTRY_SEARCH_URL)" | "$(PYTHON)" -c 'import json, sys; version = "$(PACKAGE_VERSION)"; data = json.load(sys.stdin); sys.exit(0 if any(item.get("server", {}).get("version") == version for item in data.get("servers", [])) else 1)' >/dev/null 2>&1; then \
		printf "\033[1;32m[OK]\033[0m MCP Registry metadata already exists: %s %s\n" "$(MCP_REGISTRY_NAME)" "$(PACKAGE_VERSION)"; \
	else \
		command -v mcp-publisher >/dev/null 2>&1 || { printf "\033[1;31m[ERROR]\033[0m mcp-publisher is required for publish-everywhere\n" >&2; exit 2; }; \
		tmpdir="$$(mktemp -d)"; \
		cp "$(ROOT)/registry/server.json" "$$tmpdir/server.json"; \
		(cd "$$tmpdir" && mcp-publisher login github-oidc && mcp-publisher publish); \
	fi
	$(call log_success,"MCP Registry publish target completed")
