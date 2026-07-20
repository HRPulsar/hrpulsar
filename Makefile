.PHONY: help install install-dev lock format lint test test-unit test-integration coverage \
       run run-back run-front build migrate clean \
       seed-demo seed-reset \
       back-% front-%

PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest

BACKEND := backend
FRONTEND := frontend

# -----------------------------------------------------------------------
# Help
# -----------------------------------------------------------------------

help:
	@echo "HRPulsar — development commands"
	@echo ""
	@echo "Setup:"
	@echo "  install          Install all dependencies (backend + frontend)"
	@echo "  install-dev      Install all dev dependencies"
	@echo "  lock             Regenerate backend requirements locks (pip-compile)"
	@echo ""
	@echo "Code Quality:"
	@echo "  format           Format backend code (black + ruff --fix)"
	@echo "  lint             Lint backend (ruff + mypy) and frontend (next lint)"
	@echo ""
	@echo "Testing:"
	@echo "  test             Run ALL tests (backend + frontend)"
	@echo "  test-unit        Run unit tests (backend + frontend)"
	@echo "  test-integration Run integration tests (backend only)"
	@echo "  coverage         Run tests with coverage (backend + frontend)"
	@echo ""
	@echo "Running:"
	@echo "  run              Start both backend and frontend (parallel)"
	@echo "  run-back         Start backend only (uvicorn --reload)"
	@echo "  run-front        Start frontend only (next dev)"
	@echo "  build            Build frontend for production"
	@echo "  migrate          Run alembic migrations"
	@echo "  seed-demo        Seed demo data (Pulsar Technologies)"
	@echo "  seed-reset       Reset and re-seed demo data"
	@echo ""
	@echo "Scoped commands:"
	@echo "  back-<cmd>       Run make <cmd> in backend/  (e.g. make back-test)"
	@echo "  front-<cmd>      Run npm run <cmd> in frontend/ (e.g. make front-dev)"
	@echo ""
	@echo "Maintenance:"
	@echo "  clean            Remove caches and build artifacts"

# -----------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------

install:
	.venv/bin/pip install -r $(BACKEND)/requirements.txt
	cd $(FRONTEND) && npm install

install-dev:
	.venv/bin/pip install -r $(BACKEND)/requirements.test.txt
	cd $(FRONTEND) && npm install

# Regenerate the pip-compile locks after editing requirements*.in.
lock:
	.venv/bin/pip-compile --strip-extras $(BACKEND)/requirements.in
	.venv/bin/pip-compile --strip-extras $(BACKEND)/requirements.test.in

# -----------------------------------------------------------------------
# Code Quality
# -----------------------------------------------------------------------

format:
	cd $(BACKEND) && ../.venv/bin/black . && ../.venv/bin/ruff check --fix .

lint:
	cd $(BACKEND) && ../.venv/bin/ruff check . && ../.venv/bin/mypy .
	cd $(FRONTEND) && npm run lint

# -----------------------------------------------------------------------
# Testing
# -----------------------------------------------------------------------

test:
	cd $(BACKEND) && ../.venv/bin/pytest tests -v
	cd $(FRONTEND) && npm test

test-unit:
	cd $(BACKEND) && ../.venv/bin/pytest tests/unit -v
	cd $(FRONTEND) && npm test

test-integration:
	cd $(BACKEND) && ../.venv/bin/pytest tests/integration -v

coverage:
	cd $(BACKEND) && ../.venv/bin/pytest --cov=app --cov-report=html --cov-report=term
	cd $(FRONTEND) && npm run test:coverage

# -----------------------------------------------------------------------
# Running
# -----------------------------------------------------------------------

run:
	@echo "Starting backend (port 8100) and frontend (port 3100)..."
	@trap 'kill 0' INT; \
	(cd $(BACKEND) && ../.venv/bin/uvicorn app.main:app --reload --port 8100) & \
	(cd $(FRONTEND) && npm run dev -- --port 3100) & \
	wait

run-back:
	cd $(BACKEND) && ../.venv/bin/uvicorn app.main:app --reload --port 8100

run-front:
	cd $(FRONTEND) && npm run dev -- --port 3100

build:
	cd $(FRONTEND) && npm run build

migrate:
	cd $(BACKEND) && ../.venv/bin/alembic upgrade head

seed-demo:
	$(PYTHON) scripts/seed_demo.py

seed-reset:
	$(PYTHON) scripts/seed_demo.py --reset

# -----------------------------------------------------------------------
# Scoped pass-through
# -----------------------------------------------------------------------

back-%:
	cd $(BACKEND) && $(MAKE) $*

front-%:
	cd $(FRONTEND) && npm run $*

# -----------------------------------------------------------------------
# Clean
# -----------------------------------------------------------------------

clean:
	cd $(BACKEND) && rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
	cd $(BACKEND) && find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	cd $(BACKEND) && find . -type f -name "*.pyc" -delete 2>/dev/null || true
	cd $(FRONTEND) && rm -rf .next node_modules/.cache
