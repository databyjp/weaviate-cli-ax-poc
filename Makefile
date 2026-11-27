.PHONY: format lint typecheck test install-dev

build:
	python -m build

build-check:
	python -m twine check dist/*

install-dev:
	pip install -r requirements-dev.txt
	pre-commit install

format:
	ruff format cli.py weaviate_cli test

lint:
	ruff check cli.py weaviate_cli test
	ruff format --check cli.py weaviate_cli test

typecheck:
	pyright --pythonpath "$$(command -v python)"

test:
	pytest test/unittests

build-all: build build-check

all: format lint test build-all
