.PHONY: help dev down logs migrate revision shell-world shell-gateway test

help:
	@echo "make dev        - bring up all services"
	@echo "make down       - stop all services"
	@echo "make logs       - tail logs from all services"
	@echo "make migrate    - run alembic migrations on world-api"
	@echo "make revision m='message' - create a new alembic revision"
	@echo "make shell-world   - shell into world-api container"
	@echo "make shell-gateway - shell into llm-gateway container"

dev:
	docker compose up -d --build

down:
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
