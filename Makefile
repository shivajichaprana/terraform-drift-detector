## Terraform Drift Detector — Makefile
##
## Convenience targets for developer and CI workflows.
## Run `make help` to see all available targets.

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PYTHON        ?= python3
PIP           ?= pip3
PYTEST        ?= pytest
FLAKE8        ?= flake8
MYPY          ?= mypy
DOCKER        ?= docker

PACKAGE       := detector
TESTS_DIR     := tests
CONFIG_FILE   ?= config.yaml
OUTPUT_DIR    ?= drift-results

IMAGE_NAME    ?= terraform-drift-detector
IMAGE_TAG     ?= latest
IMAGE         := $(IMAGE_NAME):$(IMAGE_TAG)

# Color output for help target
BOLD  := \033[1m
RESET := \033[0m
CYAN  := \033[36m

.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

.PHONY: help
help: ## Show this help message
	@echo "$(BOLD)Terraform Drift Detector$(RESET)"
	@echo ""
	@echo "Usage: make $(CYAN)<target>$(RESET)"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  $(CYAN)%-18s$(RESET) %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

.PHONY: install
install: ## Install the package and runtime dependencies
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	$(PIP) install -e .

.PHONY: install-dev
install-dev: install ## Install with dev dependencies (pytest, flake8, mypy)
	$(PIP) install pytest pytest-cov flake8 mypy types-PyYAML types-requests

# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------

.PHONY: lint
lint: ## Run flake8 and mypy static analysis
	$(FLAKE8) $(PACKAGE) $(TESTS_DIR) --max-line-length=120 --extend-ignore=E203,W503
	$(MYPY) $(PACKAGE) --ignore-missing-imports --no-strict-optional

.PHONY: fmt-check
fmt-check: ## Verify code formatting (flake8 only — no formatter enforced yet)
	$(FLAKE8) $(PACKAGE) $(TESTS_DIR) --max-line-length=120 --extend-ignore=E203,W503

.PHONY: test
test: ## Run the full unit test suite
	$(PYTEST) $(TESTS_DIR) -v

.PHONY: test-cov
test-cov: ## Run tests with coverage report
	$(PYTEST) $(TESTS_DIR) -v --cov=$(PACKAGE) --cov-report=term-missing --cov-report=xml

.PHONY: check
check: lint test ## Run lint and tests (primary pre-push gate)

# ---------------------------------------------------------------------------
# Runtime targets
# ---------------------------------------------------------------------------

.PHONY: detect
detect: ## Run drift detection using $(CONFIG_FILE)
	$(PYTHON) -m $(PACKAGE) detect --config $(CONFIG_FILE) --output-dir $(OUTPUT_DIR)

.PHONY: detect-json
detect-json: ## Run drift detection with JSON output
	$(PYTHON) -m $(PACKAGE) detect --config $(CONFIG_FILE) --output-format json --output-dir $(OUTPUT_DIR)

.PHONY: detect-markdown
detect-markdown: ## Run drift detection with Markdown output
	$(PYTHON) -m $(PACKAGE) detect --config $(CONFIG_FILE) --output-format markdown --output-dir $(OUTPUT_DIR)

.PHONY: report
report: ## Generate a report from the most recent drift results
	$(PYTHON) -m $(PACKAGE) report --input-dir $(OUTPUT_DIR)

# ---------------------------------------------------------------------------
# Docker targets
# ---------------------------------------------------------------------------

.PHONY: docker-build
docker-build: ## Build the drift-detector Docker image
	$(DOCKER) build -t $(IMAGE) .

.PHONY: docker-detect
docker-detect: ## Run drift detection inside the Docker image
	$(DOCKER) run --rm \
		-v $(PWD)/$(CONFIG_FILE):/app/config.yaml:ro \
		-v $(PWD)/$(OUTPUT_DIR):/app/drift-results \
		-e SLACK_WEBHOOK_URL \
		-e GITHUB_TOKEN \
		$(IMAGE) detect --config /app/config.yaml --output-dir /app/drift-results

.PHONY: docker-push
docker-push: docker-build ## Push the image to the configured registry
	$(DOCKER) push $(IMAGE)

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

.PHONY: clean
clean: ## Remove build artifacts, caches, and drift output
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .coverage coverage.xml htmlcov
	rm -rf $(OUTPUT_DIR)
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete 2>/dev/null || true

.PHONY: dist
dist: clean ## Build source and wheel distributions
	$(PYTHON) setup.py sdist bdist_wheel

.PHONY: version
version: ## Print the package version from setup.py
	@$(PYTHON) -c "import re, pathlib; m = re.search(r'version=\"([^\"]+)\"', pathlib.Path('setup.py').read_text()); print(m.group(1) if m else 'unknown')"
