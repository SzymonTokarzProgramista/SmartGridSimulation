.PHONY: install test run project report docker-up docker-project

install:
	pip install -e ".[dev,report]"

test:
	pytest

run:
	uvicorn smart_grid.api:app --reload --host 0.0.0.0 --port 8000

project:
	python scripts/run_project.py

report:
	python scripts/run_project.py --write-report

docker-up:
	docker compose up --build api

docker-project:
	docker compose --profile tools run --rm project
