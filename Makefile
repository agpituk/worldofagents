.PHONY: help start stop logs migrate revision shell-world shell-gateway test test-cov test-cov-sdk test-cov-gateway test-cov-all

help:
	@echo "make start        - bring up all services"
	@echo "make stop         - stop all services"
	@echo "make logs         - tail logs from all services"
	@echo "make migrate      - run alembic migrations on world-api"
	@echo "make revision m='message' - create a new alembic revision"
	@echo "make shell-world  - shell into world-api container"
	@echo "make shell-gateway - shell into llm-gateway container"
	@echo "make test         - run world-api pytest"
	@echo "make test-cov     - run world-api pytest with coverage"
	@echo "make test-cov-sdk - run bot-sdk-python pytest with coverage"
	@echo "make test-cov-gateway - run llm-gateway pytest with coverage"
	@echo "make test-cov-all - run coverage across all Python services"

start:
	docker compose up -d --build

stop:
	docker compose down

logs:
	docker compose logs -f --tail=100

migrate:
	docker compose exec world-api alembic upgrade head

revision:
	docker compose exec world-api alembic revision --autogenerate -m "$(m)"

shell-world:
	docker compose exec world-api bash

shell-gateway:
	docker compose exec llm-gateway bash

test:
	docker compose exec world-api pytest

# Coverage targets. world-api runs inside its container (which has the venv
# with pytest-cov); bot-sdk and llm-gateway run on the host via uv.
test-cov:
	docker compose exec world-api pytest --cov=app --cov-report=term-missing -q

test-cov-sdk:
	cd bot-sdk-python && uv run pytest --cov=src/arena_bot --cov-report=term-missing -q

test-cov-gateway:
	cd llm-gateway && uv run pytest --cov=app --cov-report=term-missing -q

test-cov-all: test-cov test-cov-sdk test-cov-gateway
