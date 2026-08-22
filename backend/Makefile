.DEFAULT_GOAL := help
COMPOSE := docker compose
PY := .venv/bin/python

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --- Local development ------------------------------------------------------
venv: ## Create the virtualenv and install dev dependencies
	python3 -m venv .venv && $(PY) -m pip install -U pip && $(PY) -m pip install -r requirements-dev.txt

browsers: ## Install the Chromium build used by the card renderer
	$(PY) -m playwright install --with-deps chromium

api: ## Run the API with autoreload
	.venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

bot: ## Run the Telegram bot (long polling)
	$(PY) -m app.bot.main

worker: ## Run a Celery worker for every queue
	.venv/bin/celery -A app.tasks.celery_app worker -Q generation,publishing,default -c 2 --loglevel=INFO

beat: ## Run the Celery beat scheduler
	.venv/bin/celery -A app.tasks.celery_app beat --loglevel=INFO

seed: ## Insert a demo education-centre business
	$(PY) scripts/seed.py

# --- Database ---------------------------------------------------------------
migrate: ## Apply all migrations
	.venv/bin/alembic upgrade head

migration: ## Create a migration: make migration m="add x"
	.venv/bin/alembic revision --autogenerate -m "$(m)"

downgrade: ## Roll back one migration
	.venv/bin/alembic downgrade -1

db-check: ## Fail if models and migrations have drifted apart
	.venv/bin/alembic check

# --- Quality ----------------------------------------------------------------
test: ## Run the test suite
	$(PY) -m pytest

cov: ## Run tests with a coverage report
	$(PY) -m pytest --cov=app --cov-report=term-missing --cov-report=html

lint: ## Lint with ruff
	.venv/bin/ruff check app tests

fmt: ## Auto-fix lint issues and format
	.venv/bin/ruff check --fix app tests && .venv/bin/ruff format app tests

typecheck: ## Static type check
	.venv/bin/mypy app

check: lint test ## Lint + test

# --- Docker -----------------------------------------------------------------
up: ## Start the whole stack
	$(COMPOSE) up -d --build

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Tail all logs
	$(COMPOSE) logs -f --tail=100

ps: ## Show container status
	$(COMPOSE) ps

restart: ## Rebuild and restart the app containers
	$(COMPOSE) up -d --build api worker-generation worker-publishing beat bot

shell: ## Open a shell inside the API container
	$(COMPOSE) exec api bash

clean: ## Remove caches and build artefacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} + ; rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage

.PHONY: help venv browsers api bot worker beat seed migrate migration downgrade db-check test cov lint fmt typecheck check up down logs ps restart shell clean
