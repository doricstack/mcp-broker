# mcp-broker - central MCP process broker

.PHONY: help

SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

include $(ROOT)/mk/config.mk
include $(ROOT)/mk/logging.mk
include $(ROOT)/mk/bootstrap.mk
include $(ROOT)/mk/tests.mk
include $(ROOT)/mk/runtime.mk
include $(ROOT)/mk/distribution.mk
include $(ROOT)/mk/maintainer.mk
include $(ROOT)/mk/release.mk

help:
	@echo "mcp-broker targets"
	@echo ""
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

-include $(ROOT)/local.mk
