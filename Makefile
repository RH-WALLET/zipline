.PHONY: up down logs build engine-test engine-lint web-test web-lint web-build e2e cycle reconcile status test lint

ENGINE := services/engine
WEB := apps/web
PY := $(ENGINE)/.venv/bin

up:                ## start the whole stack (db, engine, worker, web)
	docker compose up -d --build

down:              ## stop everything (keeps volumes)
	docker compose down

logs:
	docker compose logs -f --tail=200

build:
	docker compose build

cycle:             ## run one strategy cycle inside the engine container
	docker compose exec engine zl run-cycle

reconcile:
	docker compose exec engine zl reconcile

status:
	docker compose exec engine zl status

engine-test:
	cd $(ENGINE) && .venv/bin/pytest -q -p no:warnings

engine-lint:
	cd $(ENGINE) && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy zipline_engine

web-test:
	cd $(WEB) && pnpm test

web-lint:
	cd $(WEB) && pnpm lint && pnpm typecheck

web-build:
	cd $(WEB) && pnpm build

e2e:               ## Playwright smoke tests against a running stack on :3000
	cd $(WEB) && pnpm e2e

test: engine-test web-test
lint: engine-lint web-lint
