#------ Main Targets ------#

.DEFAULT_GOAL := help

help: ## Show this help
	@echo "Available targets:"
	@awk 'BEGIN {FS = ":.*?## "}; \
	       /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: install
install: ## Install runtime and dev dependencies
	@uv sync --locked

.PHONY: update-deps
update-deps: ## Update dependencies in uv.lock
	@uv lock --upgrade

.PHONY: unit-tests
unit-tests: ## Run unit tests
	@uv run pytest src

.PHONY: integration-tests
integration-tests: ## Run deterministic integration tests against the apac.acme.test sandbox tenant on internal Flightdeck. Requires DOPE_MCP_TESTS_CLIENT_SECRET.
	@uv run pytest tests/integration -v

.PHONY: lint
lint: ## Run ruff lint checks
	@uv run ruff check .

.PHONY: format
format: ## Apply ruff auto-fixes
	@uv run ruff check --fix .

.PHONY: typecheck
typecheck: ## Run mypy type checks
	@uv run mypy src

.PHONY: check
check: lint typecheck unit-tests ## Run lint, typecheck, and unit tests

.PHONY: inspect
inspect: ## Launch the MCP Inspector against the local server (requires npx; reads DOPE_CLIENT_ID/SECRET). Logs are also written to /tmp/dopesecurity-mcp-server.log; tail with: tail -f /tmp/dopesecurity-mcp-server.log
	@echo "Server logs: tail -f /tmp/dopesecurity-mcp-server.log"
	@npx -y @modelcontextprotocol/inspector \
		-e DOPE_CLIENT_ID="$$DOPE_CLIENT_ID" \
		-e DOPE_CLIENT_SECRET="$$DOPE_CLIENT_SECRET" \
		-e DOPE_BASE_URL=https://api.flightdeck.internal.swg.ai/v1 \
		-e DOPE_LOG_LEVEL=DEBUG \
		-e DOPE_LOG_FILE=/tmp/dopesecurity-mcp-server.log \
		-- uv run dopesecurity-mcp-server

.PHONY: clean
clean: ## Delete caches and build artifacts
	rm -rf .venv dist build *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} + > /dev/null 2>&1 || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + > /dev/null 2>&1 || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + > /dev/null 2>&1 || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + > /dev/null 2>&1 || true
