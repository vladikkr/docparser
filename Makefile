.PHONY: help install test lint format migrate seed dev up down logs clean

# Default target
help:
	@echo "DocParser.ru - Development Commands"
	@echo ""
	@echo "Setup:"
	@echo "  install       Install dependencies with Poetry"
	@echo "  migrate       Run database migrations"
	@echo "  seed          Seed database with test data"
	@echo ""
	@echo "Development:"
	@echo "  dev           Start full dev environment (Docker)"
	@echo "  up            Start Docker services"
	@echo "  down          Stop Docker services"
	@echo "  logs          View Docker logs"
	@echo "  api           Run API locally (requires services)"
	@echo "  worker        Run Celery worker locally"
	@echo ""
	@echo "Code Quality:"
	@echo "  test          Run all tests"
	@echo "  test-unit     Run unit tests only"
	@echo "  test-int      Run integration tests only"
	@echo "  lint          Run Ruff linter"
	@echo "  format        Format code with Ruff"
	@echo "  typecheck     Run MyPy type checking"
	@echo ""
	@echo "Maintenance:"
	@echo "  clean         Clean cache and build artifacts"
	@echo "  rebuild       Full rebuild (clean + install + migrate)"

# Setup
install:
	poetry install --no-interaction

migrate:
	poetry run alembic upgrade head

seed:
	poetry run python scripts/seed.py

# Development
dev:
	./scripts/dev.sh

up:
	docker-compose -f docker/docker-compose.yml up -d

down:
	docker-compose -f docker/docker-compose.yml down

logs:
	docker-compose -f docker/docker-compose.yml logs -f

api:
	poetry run uvicorn app.main:app --reload

worker:
	poetry run celery -A app.tasks.celery_app worker --loglevel=info --queues=parsing,maintenance

flower:
	poetry run celery -A app.tasks.celery_app flower --port=5555

# Code Quality
test:
	poetry run pytest --cov=app --cov-report=term-missing

test-unit:
	poetry run pytest tests/unit -v

test-int:
	poetry run pytest tests/integration -v

lint:
	poetry run ruff check .

format:
	poetry run ruff check --fix .

typecheck:
	poetry run mypy app

# Maintenance
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .coverage coverage.xml dist build *.egg-info 2>/dev/null || true

rebuild: clean install migrate seed