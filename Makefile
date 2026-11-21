PY ?= python

.PHONY: install up down migrate run worker test cov lint format typecheck check

install:
	$(PY) -m pip install -r requirements/dev.txt

up:
	docker compose up -d --wait

down:
	docker compose down

migrate:
	$(PY) manage.py migrate

run:
	$(PY) manage.py runserver

worker:
	celery -A config worker -l info -Q expedientes

test:
	pytest

cov:
	pytest --cov=apps --cov-report=term-missing

lint:
	ruff check .
	ruff format --check .

format:
	ruff check --fix .
	ruff format .

typecheck:
	mypy apps config

check:
	$(PY) manage.py check
