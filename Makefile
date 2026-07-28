# Makefile — local staging environment for yasargold
#
# Schema management:
#   Commerce API — Alembic (apps/commerce-api/alembic/), run by commerce-migrate service.
#   ERP          — db.create_all() on startup (existing pattern, unchanged).
#
# Never connect to any production system — see docs/runbooks/local-staging.md.
#
# Prerequisites: Docker Desktop (or Docker Engine + Compose plugin), psql, curl.

COMPOSE     := docker compose -f docker-compose.local.yml
ERP_DB_URL  := postgresql://erp:erp_dev@localhost:5433/yasargold_erp
COM_DB_URL  := postgresql://commerce:commerce_dev@localhost:5434/yasargold_commerce

.PHONY: up up-debug down reset logs smoke seed-admin web web-host migrate

## Start all services (builds images if needed; runs Alembic migration on first boot)
up:
	$(COMPOSE) up -d --build
	@echo ""
	@echo "Waiting for services to be healthy..."
	@$(COMPOSE) ps
	@echo ""
	@echo "  Storefront   → http://localhost:3001"
	@echo "  Commerce API → http://localhost:8000/docs"
	@echo "  ERP          → internal only  (run 'make up-debug' to expose /apidocs)"
	@echo ""
	@echo "Run 'make smoke' to verify the deployment."

## Start all services + ERP on port 8001 + /apidocs (dev inspection only)
## ERP port is NOT published in the default stack — this mirrors production §1.3.
up-debug:
	$(COMPOSE) --profile debug up -d --build
	@echo ""
	@echo "  Storefront      → http://localhost:3001"
	@echo "  ERP Swagger     → http://localhost:8001/apidocs  (debug profile)"
	@echo "  Commerce API    → http://localhost:8000/docs"
	@echo ""

## Stop all services (preserves volumes / data)
down:
	$(COMPOSE) down

## Run Commerce Alembic migrations only (useful after a migration is added)
migrate:
	$(COMPOSE) run --rm commerce-migrate

## Full reset: destroy volumes, rebuild images, migrate, seed
##
## Order:
##   1. Postgres containers start — DBs are empty
##   2. commerce-migrate runs Alembic (explicit deploy step, not lifespan)
##   3. ERP starts and calls db.create_all() (unchanged ERP pattern)
##   4. Commerce API starts (schema already exists from step 2)
##   5. Workers start
##   6. Seed SQL is loaded via psql (idempotent — ON CONFLICT DO NOTHING)
##   7. Admin user is created via Python (werkzeug hash)
reset:
	$(COMPOSE) down -v --remove-orphans
	$(COMPOSE) up -d --build postgres-erp postgres-commerce redis
	@echo "Waiting for databases to be ready..."
	@$(COMPOSE) exec -T postgres-erp  sh -c 'until pg_isready -U erp -d yasargold_erp; do sleep 1; done'
	@$(COMPOSE) exec -T postgres-commerce sh -c 'until pg_isready -U commerce -d yasargold_commerce; do sleep 1; done'
	@echo "Running Commerce API Alembic migrations..."
	$(COMPOSE) run --rm commerce-migrate
	@echo "Starting ERP (applies db.create_all schema)..."
	$(COMPOSE) up -d erp
	@$(COMPOSE) exec -T erp sh -c 'until python -c "import urllib.request; urllib.request.urlopen(\"http://localhost:8001/health\")" 2>/dev/null; do sleep 2; done'
	@echo "Starting Commerce API and workers..."
	$(COMPOSE) up -d commerce workers
	@$(COMPOSE) exec -T commerce sh -c 'until python -c "import urllib.request; urllib.request.urlopen(\"http://localhost:8000/health\")" 2>/dev/null; do sleep 2; done'
	@echo "Seeding ERP database..."
	PGPASSWORD=erp_dev psql $(ERP_DB_URL) -f seed/erp_seed.sql
	@echo "Seeding Commerce database..."
	PGPASSWORD=commerce_dev psql $(COM_DB_URL) -f seed/commerce_seed.sql
	@$(MAKE) seed-admin
	@echo "Starting storefront..."
	$(COMPOSE) up -d web
	@echo ""
	@echo "Reset complete."
	@echo ""
	@echo "  Storefront   → http://localhost:3001"
	@echo "  Commerce API → http://localhost:8000/docs"
	@echo "  ERP          → internal only  (run 'make up-debug' to expose /apidocs)"
	@echo ""
	@echo "Run 'make smoke' to verify."

define SEED_ADMIN_PY
import sys
sys.path.insert(0, '/app/backend')
from app import app
from models import db, User
with app.app_context():
    if not User.query.filter_by(username='admin').first():
        u = User(username='admin', full_name='مدير النظام', is_admin=True)
        u.set_password('admin123')
        db.session.add(u)
        db.session.commit()
        print('admin user created')
    else:
        print('admin user already exists')
endef
export SEED_ADMIN_PY

## Create the ERP admin user (username: admin, password: admin123)
## Uses Python + werkzeug so the password hash is correct — cannot do this in SQL portably.
seed-admin:
	@echo "$$SEED_ADMIN_PY" | $(COMPOSE) exec -T erp python -

## Follow logs for all services (Ctrl-C to stop)
logs:
	$(COMPOSE) logs -f

## Smoke test: verify all services respond and seed data is visible
smoke:
	@echo "── Commerce API health ──────────────────────────────────"
	curl -sf http://localhost:8000/health | python3 -m json.tool
	@echo ""
	@echo "── Catalog (seeded items) ───────────────────────────────"
	curl -sf "http://localhost:8000/api/v1/catalog/products" | python3 -m json.tool | head -40
	@echo ""
	@echo "── ERP health (via commerce network) ───────────────────"
	$(COMPOSE) exec -T commerce python -c \
	  "import urllib.request; r = urllib.request.urlopen('http://erp:8001/health'); print(r.read().decode())"
	@echo ""
	@echo "── Two-DB confirmation ──────────────────────────────────"
	@echo "Commerce DB items:"
	PGPASSWORD=commerce_dev psql $(COM_DB_URL) -c "SELECT id, item_code, name, stock FROM item ORDER BY id;" 2>/dev/null
	@echo "ERP DB items:"
	PGPASSWORD=erp_dev psql $(ERP_DB_URL) -c "SELECT id, item_code, name, stock FROM item ORDER BY id;" 2>/dev/null
	@echo ""
	@echo "── Alembic migration state ──────────────────────────────"
	DATABASE_URL=$(COM_DB_URL) PGPASSWORD=commerce_dev sh -c \
	  'cd apps/commerce-api && alembic current 2>/dev/null || echo "(alembic not installed locally; run make migrate)"'
	@echo ""
	@echo "Smoke PASSED ✓"

## Run the Next.js storefront in dev mode directly on the host (faster HMR,
## no Docker overhead).  Use this when iterating on frontend code.
## The Docker web service (make up) is for full-stack integration testing.
web-host:
	NEXT_PUBLIC_COMMERCE_API=http://localhost:8000 pnpm --filter web dev
