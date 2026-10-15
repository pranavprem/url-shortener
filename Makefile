.PHONY: install test lint format run

install:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements-dev.txt

test:
	python3 -m pytest

lint:
	python3 -m ruff check .
	python3 -m ruff format --check .

format:
	python3 -m ruff format .
	python3 -m ruff check --fix .

run:
	python3 local_server.py
