#!/bin/bash
# Start both backend and devtools frontend for local development.
#
# Usage:
#   ./scripts/dev.sh          # Start both servers
#   ./scripts/dev.sh backend  # Start backend only
#   ./scripts/dev.sh devtools # Start devtools only
#
# Backend:  http://localhost:8000  (FastAPI + Swagger at /docs)
# DevTools: http://localhost:5174  (Svelte dev server, proxies /api → backend)

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Change to project root
cd "$(dirname "$0")/.."

# Check .env exists
if [ ! -f .env ]; then
    echo -e "${RED}❌ No .env file found.${NC}"
    echo "   Run: cp .env.example .env && edit .env"
    exit 1
fi

start_backend() {
    echo -e "${GREEN}🚀 Starting backend on http://localhost:8000${NC}"
    echo -e "${GREEN}   Swagger docs: http://localhost:8000/docs${NC}"
    uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
}

start_devtools() {
    echo -e "${BLUE}🛠  Starting DevTools on http://localhost:5174${NC}"
    cd devtools
    npm run dev
}

case "${1:-all}" in
    backend|back|api)
        start_backend
        ;;
    devtools|dev|frontend|ui)
        start_devtools
        ;;
    all|both)
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${YELLOW}  Erleah Development Servers${NC}"
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
        echo -e "  ${GREEN}Backend:${NC}  http://localhost:8000"
        echo -e "  ${GREEN}Swagger:${NC}  http://localhost:8000/docs"
        echo -e "  ${BLUE}DevTools:${NC} http://localhost:5174"
        echo ""
        echo -e "  Press ${RED}Ctrl+C${NC} to stop both servers"
        echo ""

        # Start both in background, kill both on exit
        trap 'kill 0; exit 0' SIGINT SIGTERM

        start_backend &
        BACKEND_PID=$!

        # Small delay so backend logs don't interleave with devtools startup
        sleep 1

        start_devtools &
        DEVTOOLS_PID=$!

        # Wait for either to exit
        wait
        ;;
    *)
        echo "Usage: $0 [backend|devtools|all]"
        echo ""
        echo "  backend  - Start FastAPI backend only"
        echo "  devtools - Start Svelte DevTools only"
        echo "  all      - Start both (default)"
        exit 1
        ;;
esac
