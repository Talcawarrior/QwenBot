.PHONY: quality lint format typecheck test security install-hooks help

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

install-hooks:  ## Install pre-commit hooks
	pre-commit install

quality: lint format typecheck test  ## Run all quality checks

lint:  ## Ruff lint
	ruff check . --fix

format:  ## Ruff format
	ruff format .

typecheck:  ## Mypy type check
	mypy config/ engine/ executor/ scrapers/ utils/ database/ jobs/ --ignore-missing-imports

test:  ## Pytest + coverage
	pytest --cov --cov-report=term-missing -q

security:  ## Bandit security scan
	bandit -r config/ engine/ executor/ scrapers/ utils/ database/ jobs/ --severity-level=high -q

all: install-hooks quality security  ## Install hooks + run everything
