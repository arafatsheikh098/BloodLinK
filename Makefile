.PHONY: install test lint run migrate seed purge fresh fresh-test

install:
	python -m pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check app tests

run:
	uvicorn app:app --reload --host 0.0.0.0 --port 8000

migrate:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

seed:
	python -m app.cli seed

purge:
	python -m app.cli purge

fresh:
	alembic downgrade base && alembic upgrade head

fresh-test:
	rm -f bloodlink.db && pytest
