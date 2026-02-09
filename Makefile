# Erleah Backend — Development Commands
# ======================================
#
# Quick start:  make dev
# Backend only: make backend
# DevTools only: make devtools
# Run tests:    make test

.PHONY: dev backend devtools test setup install db

# Start both backend + DevTools (most common)
dev:
	@./scripts/dev.sh

# Start backend only (FastAPI on :8000)
backend:
	@./scripts/dev.sh backend

# Start DevTools only (Svelte on :5174)
devtools:
	@./scripts/dev.sh devtools

# Run tests
test:
	uv run python -m pytest tests/ -v

# Run a specific test file
test-file:
	uv run python -m pytest $(FILE) -v

# First-time setup
setup:
	./setup.sh

# Install Python dependencies
install:
	uv sync

# Install DevTools dependencies
install-devtools:
	cd devtools && npm install

# Start Docker databases (Postgres, Qdrant, Redis)
db:
	docker-compose up -d

# Stop Docker databases
db-stop:
	docker-compose down
