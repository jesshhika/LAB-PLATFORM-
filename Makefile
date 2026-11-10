.PHONY: up down migrate test lint validate-phase0

up:
	docker compose up --build

down:
	docker compose down

migrate:
	docker compose run --rm --no-deps api sh -c "cd /workspace/api && alembic upgrade head"

test:
	docker compose run --rm api pytest
	docker compose run --rm --no-deps guac-proxy npm test

lint:
	docker compose run --rm api ruff check --select E4,E7,E9,F,I api worker
	docker compose run --rm --no-deps web npm run lint
	docker compose run --rm --no-deps guac-proxy npm run lint

validate-phase0:
	powershell -NoProfile -ExecutionPolicy Bypass -File infra/validate-phase0.ps1
