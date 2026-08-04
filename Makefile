.PHONY: install check test lint format typecheck validate-demo

install:
	python -m pip install -e '.[dev]'

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

typecheck:
	mypy

test:
	pytest

validate-demo:
	orbitops validate scenarios/examples/demo.json
	orbitops check scenarios/examples/demo.json scenarios/examples/feasible-schedule.json
	orbitops solve scenarios/examples/demo.json --solver greedy-insertion --seed 42
	orbitops solve scenarios/tiny/tiny-conflict.json --solver branch-and-bound

check: lint typecheck test validate-demo
