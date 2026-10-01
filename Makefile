# Dindon: everyday commands. `make help` lists them.
PYTHON ?= python3.13
VENV   := .venv
BIN    := $(VENV)/bin

.PHONY: help setup up down db migrate check test axes backup

help:
	@echo "make setup    create the Python environment (.venv) and install Dindon with its test tools"
	@echo "make up       start everything with Docker (database, application)"
	@echo "make down     stop everything (data is kept)"
	@echo "make db       start the database only, to work on the code outside Docker"
	@echo "make migrate  apply the SQL files to the database"
	@echo "make check    print what the database is made of"
	@echo "make test     run all the tests (starts and removes a throwaway database)"
	@echo "make axes     rewrite docs/AXES.md from the database (page to review the axes)"
	@echo "make backup   dump the database to backups/ (compressed)"

$(BIN)/dindon: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --quiet -e ".[dev]"
	@touch $(BIN)/dindon

setup: $(BIN)/dindon

up:
	docker compose up -d --build

down:
	docker compose down

db:
	docker compose up -d --wait db

migrate: setup
	$(BIN)/dindon migrate

check: setup
	$(BIN)/dindon check

test: setup
	$(BIN)/pytest

axes: setup
	DATABASE_URL=$$($(BIN)/python -c "from dindon.config import load_settings; print(load_settings().database_url)") \
		$(BIN)/python tools/generate_axes_review.py

backup:
	@mkdir -p backups
	docker compose exec -T db pg_dump -U dindon dindon | gzip > backups/dindon-$$(date +%F-%H%M).sql.gz
	@ls -lh backups | tail -1
