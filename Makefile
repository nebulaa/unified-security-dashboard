SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PY := backend/.venv/bin/python
PIP := backend/.venv/bin/python -m pip
UV := uv
PYTHON_HOST := /usr/local/bin/python3.13

# Auto-load `.env` (and `.env.local` taking precedence) before invoking any backend
# command, so DEPENDABOT_PAT and friends are available to scripts that read
# `os.environ` directly. pydantic-settings *also* reads the file, but raw env reads
# need real env vars.
LOAD_ENV := set -a; [ -f .env.local ] && . ./.env.local; [ -f .env ] && . ./.env; set +a;

# ---------- meta ----------

help: ## Show available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_.-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------- bootstrap ----------

venv: ## Create the backend venv (Python 3.13) if missing
	@test -d backend/.venv || $(UV) venv --python $(PYTHON_HOST) backend/.venv

install: venv ## Install backend dependencies (editable + dev)
	@cd backend && ../$(PY) -m ensurepip --upgrade >/dev/null 2>&1 || true
	@cd backend && $(UV) pip install --python ../$(PY) -e ".[dev]"

# ---------- infra ----------

postgres-up: ## Start local Postgres
	docker-compose up -d postgres

postgres-down: ## Stop local Postgres (keeps volume)
	docker-compose stop postgres

postgres-reset: ## Wipe local Postgres data and re-create
	docker-compose down -v
	docker-compose up -d postgres
	@sleep 3

# ---------- schema ----------

migrate: postgres-up ## Apply Alembic migrations to local Postgres
	@cd backend && ../$(PY) -m app.migrate upgrade head

migrate-revision: ## Autogenerate a new Alembic revision (use M="message")
	@cd backend && ../$(PY) -m app.migrate revision --autogenerate -m "$(M)"

migrate-current: ## Show current Alembic revision
	@cd backend && ../$(PY) -m app.migrate current

rollup-backfill: postgres-up migrate ## Backfill daily_metrics 30d on LOCAL_DATABASE_URL (not GCP)
	@$(LOAD_ENV) \
	  LOCAL_DATABASE_URL="$${LOCAL_DATABASE_URL:-$$DATABASE_URL}"; \
	  test -n "$$LOCAL_DATABASE_URL" || { echo "Set LOCAL_DATABASE_URL or DATABASE_URL in .env.local"; exit 1; }; \
	  cd backend && DATABASE_URL="$$LOCAL_DATABASE_URL" ../$(PY) -m app.jobs.rollup --backfill-days 30

rollup-backfill-gcp: ## Backfill daily_metrics 30d on GCP_DATABASE_URL (Cloud SQL Auth Proxy)
	@$(LOAD_ENV) \
	  test -n "$${GCP_DATABASE_URL:-}" || { echo "Set GCP_DATABASE_URL in .env.local (see .env.local.example)"; exit 1; }; \
	  cd backend && DATABASE_URL="$$GCP_DATABASE_URL" ../$(PY) -m app.jobs.rollup --backfill-days 30

rollup-status: postgres-up migrate ## Print findings/daily_metrics counts on LOCAL_DATABASE_URL
	@$(LOAD_ENV) \
	  LOCAL_DATABASE_URL="$${LOCAL_DATABASE_URL:-$$DATABASE_URL}"; \
	  test -n "$$LOCAL_DATABASE_URL" || { echo "Set LOCAL_DATABASE_URL or DATABASE_URL in .env.local"; exit 1; }; \
	  cd backend && DATABASE_URL="$$LOCAL_DATABASE_URL" ../$(PY) -m app.jobs.rollup --status

rollup-status-gcp: ## Print findings/daily_metrics counts on GCP_DATABASE_URL (proxy)
	@$(LOAD_ENV) \
	  test -n "$${GCP_DATABASE_URL:-}" || { echo "Set GCP_DATABASE_URL in .env.local"; exit 1; }; \
	  cd backend && DATABASE_URL="$$GCP_DATABASE_URL" ../$(PY) -m app.jobs.rollup --status

cloud-rollup-backfill: ## Backfill daily_metrics 30d on Cloud SQL via secdb-rollup job (not .env.local)
	gcloud run jobs execute secdb-rollup \
	  --region=$(CLOUD_REGION) --project=$(CLOUD_PROJECT) --wait \
	  --args="-m,app.jobs.rollup,--backfill-days,30"

rollup-backfill-wiz: postgres-up migrate ## Backfill daily_metrics 90d (align with WIZ_BACKFILL_DAYS)
	@$(LOAD_ENV) \
	  LOCAL_DATABASE_URL="$${LOCAL_DATABASE_URL:-$$DATABASE_URL}"; \
	  test -n "$$LOCAL_DATABASE_URL" || { echo "Set LOCAL_DATABASE_URL or DATABASE_URL in .env.local"; exit 1; }; \
	  cd backend && DATABASE_URL="$$LOCAL_DATABASE_URL" ../$(PY) -m app.jobs.rollup --backfill-days 90

cloud-rollup-backfill-wiz: ## Backfill daily_metrics 90d on Cloud SQL (after Wiz --backfill poll)
	gcloud run jobs execute secdb-rollup \
	  --region=$(CLOUD_REGION) --project=$(CLOUD_PROJECT) --wait \
	  --args="-m,app.jobs.rollup,--backfill-days,90"

cloud-rollup-status: ## Print findings/daily_metrics counts on Cloud SQL (secdb-rollup job)
	gcloud run jobs execute secdb-rollup \
	  --region=$(CLOUD_REGION) --project=$(CLOUD_PROJECT) --wait \
	  --args="-m,app.jobs.rollup,--status"

ownership-reresolve: postgres-up migrate ## Re-resolve owner_team on LOCAL_DATABASE_URL (+ 30d rollup if updates)
	@$(LOAD_ENV) \
	  LOCAL_DATABASE_URL="$${LOCAL_DATABASE_URL:-$$DATABASE_URL}"; \
	  test -n "$$LOCAL_DATABASE_URL" || { echo "Set LOCAL_DATABASE_URL or DATABASE_URL in .env.local"; exit 1; }; \
	  cd backend && DATABASE_URL="$$LOCAL_DATABASE_URL" ../$(PY) -m app.jobs.ownership_reresolve

ownership-reresolve-dry-run: postgres-up migrate ## Preview ownership re-resolve without writing
	@$(LOAD_ENV) \
	  LOCAL_DATABASE_URL="$${LOCAL_DATABASE_URL:-$$DATABASE_URL}"; \
	  test -n "$$LOCAL_DATABASE_URL" || { echo "Set LOCAL_DATABASE_URL or DATABASE_URL in .env.local"; exit 1; }; \
	  cd backend && DATABASE_URL="$$LOCAL_DATABASE_URL" ../$(PY) -m app.jobs.ownership_reresolve --dry-run

ownership-reresolve-status: postgres-up migrate ## Print owner_team distribution + recent ownership_changed events
	@$(LOAD_ENV) \
	  LOCAL_DATABASE_URL="$${LOCAL_DATABASE_URL:-$$DATABASE_URL}"; \
	  test -n "$$LOCAL_DATABASE_URL" || { echo "Set LOCAL_DATABASE_URL or DATABASE_URL in .env.local"; exit 1; }; \
	  cd backend && DATABASE_URL="$$LOCAL_DATABASE_URL" ../$(PY) -m app.jobs.ownership_reresolve --status

ownership-reresolve-gcp: ## Re-resolve on GCP_DATABASE_URL via Cloud SQL Auth Proxy
	@$(LOAD_ENV) \
	  test -n "$${GCP_DATABASE_URL:-}" || { echo "Set GCP_DATABASE_URL in .env.local"; exit 1; }; \
	  cd backend && DATABASE_URL="$$GCP_DATABASE_URL" ../$(PY) -m app.jobs.ownership_reresolve

cloud-ownership-reresolve: ## Re-resolve owner_team on Cloud SQL (secdb-ownership-reresolve job)
	gcloud run jobs execute secdb-ownership-reresolve \
	  --region=$(CLOUD_REGION) --project=$(CLOUD_PROJECT) --wait \
	  --args="-m,app.jobs.ownership_reresolve"

cloud-ownership-reresolve-status: ## Print owner_team stats on Cloud SQL (ownership job --status)
	gcloud run jobs execute secdb-ownership-reresolve \
	  --region=$(CLOUD_REGION) --project=$(CLOUD_PROJECT) --wait \
	  --args="-m,app.jobs.ownership_reresolve,--status"

# ---------- Cloud Run local proxies ----------
# Use the 908x range so these never collide with local dev (:8000 API, :8001
# normalizer, :3000 frontend). Do not use 8080/8081 — Cloud Run images listen
# on 8080 internally and 8081 is easy to confuse with the normalizer on 8001.

# Export CLOUD_PROJECT (and optionally CLOUD_REGION) before cloud-* targets.
CLOUD_PROJECT ?=
CLOUD_REGION ?= europe-west1
CLOUD_PROXY_API_PORT ?= 9080
CLOUD_PROXY_FRONTEND_PORT ?= 9082

cloud-proxy-api: ## Proxy deployed secdb-api to localhost:9080
	gcloud run services proxy secdb-api \
	  --port=$(CLOUD_PROXY_API_PORT) \
	  --region=$(CLOUD_REGION) \
	  --project=$(CLOUD_PROJECT)

cloud-proxy-frontend: ## Proxy deployed secdb-frontend to localhost:9082
	gcloud run services proxy secdb-frontend \
	  --port=$(CLOUD_PROXY_FRONTEND_PORT) \
	  --region=$(CLOUD_REGION) \
	  --project=$(CLOUD_PROJECT)

# Build images (when paths changed), terraform apply, optional migrate.
# GCP_PROJECT selects deploy/terraform/*.tfvars by matching project_id.
# Examples: make cloud-deploy | make cloud-deploy ARGS="--all" | make cloud-deploy ARGS="--backend --migrate"
cloud-deploy: ## Deploy to GCP: Cloud Build + Terraform (+ optional migrate)
	@GCP_PROJECT="$(CLOUD_PROJECT)" GCP_REGION="$(CLOUD_REGION)" ./scripts/deploy-cloud.sh $(ARGS)

# ---------- run ----------

api-dev: ## Run the FastAPI API locally on :8000
	@$(LOAD_ENV) cd backend && ../$(PY) -m uvicorn app.api.main:app --reload --port 8000

normalizer-dev: ## Run the normalizer service locally on :8001
	@$(LOAD_ENV) cd backend && ../$(PY) -m uvicorn app.normalizer.main:app --reload --port 8001

rotate-dependabot-pat: ## Validate PAT and push to GSM + .env.local (see scripts/rotate-dependabot-pat.sh)
	@./scripts/rotate-dependabot-pat.sh

check-dependabot-pat: ## Print PAT scopes and test org Dependabot API access
	@./scripts/rotate-dependabot-pat.sh --check-only

poller-dependabot: ## Run the Dependabot poller once (publishes one snapshot to the local normalizer)
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.pollers.dependabot

poller-sonarcloud: ## Run the SonarCloud poller once (publishes one snapshot to the local normalizer)
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.pollers.sonarcloud

poller-wiz: ## Run the Wiz poller once (publishes one snapshot to the local normalizer)
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.pollers.wiz

poller-jira-pentest: ## Run the Jira pentest poller once
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.pollers.jira_pentest

poller-wiz-backfill: ## First Wiz poll: 90-day firstSeenAt window
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.pollers.wiz --backfill

wiz-map-inventory: ## Wiz catalog vs registry vs DB slug coverage (needs WIZ_* for live catalog)
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.cli.main wiz-map inventory

wiz-map-suggest: ## Write config/wiz_service_map.suggested.yaml
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.cli.main wiz-map suggest

wiz-map-apply: ## Apply high-confidence wiz_service mappings to component_registry.yaml
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.cli.main wiz-map apply --min-confidence high

wiz-map-reresolve: ## Re-stamp owner_team on open Wiz wizservice:* and cloudres:* findings
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.cli.main wiz-map reresolve

wiz-map-reresolve-pillar: ## Re-stamp platform_pillar:* tags on open Wiz findings
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.cli.main wiz-map reresolve-pillar

cloud-wiz-map-reresolve-pillar: ## Re-stamp platform_pillar:* on Cloud SQL (ownership job image)
	gcloud run jobs execute secdb-ownership-reresolve \
	  --region=$(CLOUD_REGION) --project=$(CLOUD_PROJECT) --wait \
	  --args="-m,app.cli.main,wiz-map,reresolve-pillar"

cloud-poller-wiz-backfill: ## One-time Wiz backfill poll on Cloud Run (not scheduled)
	gcloud run jobs execute secdb-poller-wiz \
	  --region=$(CLOUD_REGION) --project=$(CLOUD_PROJECT) --wait \
	  --args="-m,app.pollers.wiz,--backfill"

coverage-sample: ## Write a local cloud-coverage snapshot (prototype data, no cloud creds)
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.coverage.collect --sample

coverage-live: ## Collect live code coverage (GitHub + Sonar)
	@$(LOAD_ENV) cd backend && \
	  SECRET_BACKEND="$${SECRET_BACKEND:-env}" \
	  GITHUB_ORG="$${GITHUB_ORG:-ExampleOrg}" \
	  GH_TOKEN="$${GH_TOKEN:-$$(gh auth token)}" \
	  SONAR_ORGS="$${SONAR_ORGS:-exampleorg}" \
	  ../$(PY) -m app.coverage.collect

cli: ## Invoke the secdb CLI; pass args via ARGS="..." (e.g. make cli ARGS="roles list")
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.cli.main $(ARGS)

mcp-dev: ## Run the local MCP server over stdio (Claude / Cursor clients spawn it)
	@$(LOAD_ENV) cd backend && ../$(PY) -m app.mcp.server

mcp-http-dev: ## Run MCP server locally on :3001 (streamable-http, bearer auth)
	@$(LOAD_ENV) MCP_TRANSPORT=streamable-http MCP_PORT=3001 cd backend && ../$(PY) -m app.mcp.server

# Eat any extra positional goals so `make cli -- foo bar` works without "No rule" noise.
%:
	@:

# ---------- frontend ----------

frontend-install: ## Install frontend dependencies
	@cd frontend && npm install

frontend-dev: ## Run the Next.js dev server on :3000 (loads ../.env first)
	@$(LOAD_ENV) cd frontend && npm run dev

dev-as-admin: ## Frontend dev server with admin identity (./scripts/dev-as.sh)
	@./scripts/dev-as.sh admin frontend

dev-as-member: ## Frontend dev server as regular user / member identity
	@./scripts/dev-as.sh member frontend

# Prod API rejects X-Dev-Identity (IAP only). Use full local stack instead.
# frontend-dev-cloud-api: ## (disabled) prod API needs IAP, not dev headers

frontend-typecheck: ## tsc --noEmit
	@cd frontend && npm run typecheck

frontend-build: ## Production build
	@cd frontend && npm run build

# ---------- quality ----------

lint: ## Lint backend with ruff
	@cd backend && ../$(PY) -m ruff check app migrations

lint-fix: ## Lint and auto-fix
	@cd backend && ../$(PY) -m ruff check --fix app migrations

validate-config: ## Cross-check team keys across ownership.yaml, component_scope.yaml, exec-pillars.ts, component-map.ts
	@$(PY) scripts/validate_config.py

test: ## Run backend tests
	@cd backend && ../$(PY) -m pytest -q

# ---------- shortcuts ----------

bootstrap: install postgres-up migrate ## One-shot: install deps, start db, migrate

shell-db: ## Open psql against local Postgres
	docker exec -it secdb-postgres psql -U secdb -d secdb

.PHONY: help venv install postgres-up postgres-down postgres-reset migrate migrate-revision migrate-current cloud-proxy-api cloud-proxy-frontend cloud-deploy api-dev normalizer-dev rotate-dependabot-pat check-dependabot-pat poller-dependabot poller-sonarcloud poller-wiz poller-wiz-backfill cloud-poller-wiz-backfill wiz-map-inventory wiz-map-suggest wiz-map-apply wiz-map-reresolve wiz-map-reresolve-pillar cloud-wiz-map-reresolve-pillar coverage-sample coverage-live cli mcp-dev mcp-http-dev frontend-install frontend-dev dev-as-admin dev-as-member frontend-typecheck frontend-build lint lint-fix validate-config test bootstrap shell-db rollup-backfill rollup-backfill-gcp rollup-backfill-wiz cloud-rollup-backfill cloud-rollup-backfill-wiz ownership-reresolve ownership-reresolve-dry-run ownership-reresolve-status ownership-reresolve-gcp cloud-ownership-reresolve cloud-ownership-reresolve-status
