#!/usr/bin/env bash
#
# Erleah v2 Backend — Demo Script
# Shows the 9-node LangGraph pipeline in action via server logs.
#
# Usage:
#   1. Start server in another terminal:
#      .venv/bin/python -m src.main 2>&1 | tee /tmp/erleah_server.log
#   2. Run this script:
#      bash scripts/demo.sh
#
# The server logs (in the other terminal) are the main demo output.
# This script sends curated queries and shows SSE response summaries.

set -euo pipefail

API="http://localhost:8000/api/chat/stream"
CONF="etl-2025"
BOLD="\033[1m"
CYAN="\033[36m"
GREEN="\033[32m"
YELLOW="\033[33m"
DIM="\033[2m"
RESET="\033[0m"

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

banner() {
  echo ""
  echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${RESET}"
  echo -e "${BOLD}${CYAN}  DEMO $1: $2${RESET}"
  echo -e "${BOLD}${CYAN}══════════════════════════════════════════════════════════════${RESET}"
  echo -e "${DIM}  Query: \"$3\"${RESET}"
  echo -e "${DIM}  What to watch: $4${RESET}"
  echo ""
}

send_query() {
  local msg="$1"
  local user_id="${2:-}"
  local start_time=$(date +%s%3N)

  local body
  if [ -n "$user_id" ]; then
    body=$(python3 -c "
import json
print(json.dumps({
    'message': '$msg',
    'user_context': {
        'conference_id': '$CONF',
        'user_id': '$user_id'
    }
}))
")
  else
    body=$(python3 -c "
import json
print(json.dumps({
    'message': '$msg',
    'user_context': {
        'conference_id': '$CONF'
    }
}))
")
  fi

  local chunk_count=0
  local response_text=""
  local got_ack=""
  local got_done=""

  # Stream SSE and collect stats
  while IFS= read -r line; do
    if [[ "$line" == data:* ]]; then
      local data="${line#data: }"

      # Acknowledgment
      if echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('message',''))" 2>/dev/null | grep -q "help\|assist\|find\|search\|look\|let me\|I'll"; then
        got_ack=$(echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('message',''))" 2>/dev/null)
      fi

      # Chunks
      local text=$(echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); t=d.get('text',''); print(t,end='')" 2>/dev/null)
      if [ -n "$text" ]; then
        chunk_count=$((chunk_count + 1))
        response_text+="$text"
      fi

      # Done event
      if echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('trace_id',''))" 2>/dev/null | grep -q "[a-f0-9-]"; then
        local trace=$(echo "$data" | python3 -c "import json,sys; d=json.load(sys.stdin); t=d.get('trace_id',''); print(t) if t else None" 2>/dev/null)
        if [ -n "$trace" ] && [ "$trace" != "None" ]; then
          got_done="$trace"
        fi
      fi
    fi
  done < <(curl -s -N -X POST "$API" \
    -H "Content-Type: application/json" \
    -d "$body" 2>&1)

  local end_time=$(date +%s%3N)
  local elapsed=$(( (end_time - start_time) ))

  # Print summary
  echo ""
  echo -e "${GREEN}  ── Response Summary ──${RESET}"
  if [ -n "$got_ack" ]; then
    echo -e "  ${DIM}Acknowledgment: ${got_ack}${RESET}"
  fi
  echo -e "  ${BOLD}Chunks: ${chunk_count}  |  Time: ${elapsed}ms  |  Trace: ${got_done:-n/a}${RESET}"
  echo ""
  # Show first 300 chars of response
  local preview=$(echo "$response_text" | head -c 400)
  echo -e "  ${DIM}Response preview:${RESET}"
  echo -e "  ${preview}"
  echo ""
}

wait_for_enter() {
  echo -e "${YELLOW}  Press ENTER to run this query...${RESET}"
  read -r
}

# ─────────────────────────────────────────────
# Pre-flight check
# ─────────────────────────────────────────────

echo ""
echo -e "${BOLD}Erleah v2 Backend — Pipeline Demo${RESET}"
echo -e "${DIM}Conference: ETL 2025  |  Pipeline: 9-node LangGraph${RESET}"
echo ""

# Check server is running
if ! curl -s http://localhost:8000/ > /dev/null 2>&1; then
  echo -e "\033[31mERROR: Server not running on :8000${RESET}"
  echo "Start it with:  .venv/bin/python -m src.main 2>&1 | tee /tmp/erleah_server.log"
  exit 1
fi
echo -e "${GREEN}Server is running.${RESET}"
echo ""

# ─────────────────────────────────────────────
# DEMO 1: Exhibitor search (faceted search)
# ─────────────────────────────────────────────

banner "1/5" "Exhibitor Faceted Search" \
  "Find exhibitors with event registration solutions" \
  "NODE 4 (plan_queries) -> NODE 5 (execute_queries with FACETED search) -> scoring formula"

wait_for_enter
send_query "Find exhibitors with event registration solutions"

# ─────────────────────────────────────────────
# DEMO 2: Session search (different entity type)
# ─────────────────────────────────────────────

banner "2/5" "Session Search" \
  "What sessions cover AI and machine learning?" \
  "NODE 4 plans a SESSIONS table query -> NODE 5 searches sessions_facets"

wait_for_enter
send_query "What sessions cover AI and machine learning?"

# ─────────────────────────────────────────────
# DEMO 3: Speaker search
# ─────────────────────────────────────────────

banner "3/5" "Speaker Search" \
  "Who are the keynote speakers about sustainability?" \
  "NODE 5 searches speakers_facets -> scoring with breadth/depth"

wait_for_enter
send_query "Who are the keynote speakers about sustainability?"

# ─────────────────────────────────────────────
# DEMO 4: Multi-table hybrid search
# ─────────────────────────────────────────────

banner "4/5" "Multi-Table Hybrid Search" \
  "I want to learn about event technology trends, any sessions or exhibitors?" \
  "NODE 4 plans MULTIPLE queries (sessions + exhibitors) -> parallel execution"

wait_for_enter
send_query "I want to learn about event technology trends, any sessions or exhibitors?"

# ─────────────────────────────────────────────
# DEMO 5: Narrow query (may trigger retry)
# ─────────────────────────────────────────────

banner "5/5" "Retry Flow — Narrow Query" \
  "Are there any exhibitors selling quantum computing hardware?" \
  "NODE 6 (check_results) detects 0 results -> NODE 6b (relax_and_retry) lowers threshold"

wait_for_enter
send_query "Are there any exhibitors selling quantum computing hardware?"

# ─────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────

echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}${GREEN}  DEMO COMPLETE${RESET}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════════════════${RESET}"
echo ""
echo -e "${DIM}  Check server logs for full pipeline trace:${RESET}"
echo -e "${DIM}  tail -f /tmp/erleah_server.log | python3 -m json.tool${RESET}"
echo ""
