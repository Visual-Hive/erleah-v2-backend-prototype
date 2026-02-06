#!/usr/bin/env python3
"""
Pretty-print Erleah server logs for demo.

Usage:
  # Live tail:
  tail -f /tmp/erleah_server.log | .venv/bin/python scripts/log_viewer.py

  # Or replay a log file:
  .venv/bin/python scripts/log_viewer.py /tmp/erleah_server.log
"""

import json
import sys

# ANSI colors
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
RESET = "\033[0m"

# Node banners get special treatment
NODE_COLORS = {
    "NODE 1": CYAN,
    "NODE 2": CYAN,
    "NODE 3": MAGENTA,
    "NODE 4": BLUE,
    "NODE 5": GREEN,
    "NODE 6": YELLOW,
    "NODE 6b": YELLOW,
    "NODE 7": GREEN,
    "NODE 8": DIM,
}


def format_line(line: str) -> str | None:
    """Format a single log line for display."""
    line = line.strip()
    if not line:
        return None

    # Skip uvicorn access logs and non-JSON
    if line.startswith("INFO:") or line.startswith("WARNING:  Watch"):
        return None

    # Try to parse JSON
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        # Non-JSON line (uvicorn startup messages etc)
        if any(
            x in line
            for x in ["Started server", "Application startup", "Shutting down"]
        ):
            return f"{DIM}{line}{RESET}"
        return None

    event = data.get("event", "")
    level = data.get("level", "info")
    trace = data.get("trace_id", "")
    ts = data.get("timestamp", "")

    # Extract short timestamp (just HH:MM:SS)
    short_ts = ts[11:19] if len(ts) > 19 else ""

    # Color based on level
    level_color = {
        "info": "",
        "warning": YELLOW,
        "error": RED,
    }.get(level, "")

    # ── Pipeline banners ──
    if "PIPELINE START" in event:
        msg = data.get("message", "")
        return (
            f"\n{BOLD}{CYAN}{'═' * 70}{RESET}\n"
            f"{BOLD}{CYAN}  PIPELINE START{RESET}  {short_ts}\n"
            f'  Query: {WHITE}"{msg}"{RESET}\n'
            f"  Trace: {DIM}{trace}{RESET}\n"
            f"{BOLD}{CYAN}{'═' * 70}{RESET}"
        )

    if "PIPELINE COMPLETE" in event:
        dur = data.get("total_duration", "?")
        chunks = data.get("chunks_streamed", 0)
        nodes = data.get("nodes_visited", [])
        return (
            f"\n{BOLD}{GREEN}{'═' * 70}{RESET}\n"
            f"{BOLD}{GREEN}  PIPELINE COMPLETE{RESET}  {dur}  |  {chunks} chunks  |  {len(nodes)} nodes\n"
            f"  Nodes: {' -> '.join(nodes)}\n"
            f"{BOLD}{GREEN}{'═' * 70}{RESET}\n"
        )

    # ── SSE REQUEST banner ──
    if "SSE REQUEST" in event:
        conf = data.get("conference_id", "?")
        preview = data.get("message_preview", "")
        return (
            f"\n{BOLD}{MAGENTA}{'─' * 70}{RESET}\n"
            f"{BOLD}{MAGENTA}  SSE REQUEST{RESET}  conference={conf}\n"
            f'  "{preview}"\n'
            f"{BOLD}{MAGENTA}{'─' * 70}{RESET}"
        )

    # ── Node banners ──
    for node_key, color in NODE_COLORS.items():
        if f"===== {node_key}:" in event and "COMPLETE" not in event:
            return f"\n{BOLD}{color}  ▶ {event.strip('= ')}{RESET}"
        if f"===== {node_key}:" in event and "COMPLETE" in event:
            # Extract key metrics from the data
            extras = []
            for k in [
                "has_profile",
                "intent",
                "query_mode",
                "num_queries",
                "total_results",
                "needs_retry",
                "retry_count",
                "quality_score",
                "confidence_score",
                "response_length",
                "acknowledgment",
                "zero_result_tables",
                "verdict",
            ]:
                if k in data:
                    extras.append(f"{k}={data[k]}")
            extra_str = f"  {DIM}({', '.join(extras)}){RESET}" if extras else ""
            return f"{color}  ✓ {event.strip('= ')}{RESET}{extra_str}"

    # ── Conditional edges ──
    if "[conditional]" in event:
        decision = data.get("decision", "?")
        return f"  {YELLOW}⤷ {event.strip()}{RESET}  →  {BOLD}{decision}{RESET}"

    # ── Search details ──
    if "[SEARCH]" in event:
        if "Top #" in event:
            return f"    {GREEN}{event.strip()}{RESET}"
        if "Scoring complete" in event or "faceted_search complete" in event:
            return f"  {GREEN}{event.strip()}{RESET}"
        if "Strategy:" in event:
            return f"  {CYAN}{event.strip()}{RESET}"
        return f"  {DIM}{event.strip()}{RESET}"

    # ── LLM usage ──
    if "[llm_usage]" in event:
        model = data.get("model", "?")
        node = data.get("node", "?")
        inp = data.get("input_tokens", 0)
        out = data.get("output_tokens", 0)
        cached = data.get("cached_tokens", 0)
        cache_str = f" cached={cached}" if cached else ""
        return f"  {BLUE}⚡ LLM: {model} @ {node}  in={inp} out={out}{cache_str}{RESET}"

    # ── SSE events ──
    if "[sse]" in event:
        if "first chunk" in event:
            ttfc = data.get("time_to_first_chunk", "?")
            return f"  {GREEN}⚡ First chunk sent at {ttfc}{RESET}"
        if "done event" in event:
            elapsed = data.get("elapsed", "?")
            chunks = data.get("chunks_streamed", 0)
            return f"  {GREEN}✓ Done — {chunks} chunks in {elapsed}{RESET}"
        if "acknowledgment event" in event:
            text = data.get("text", "")
            return f'  {MAGENTA}💬 Ack: "{text}"{RESET}'
        return None  # Skip other SSE noise

    # ── Qdrant search ──
    if "[qdrant] search complete" in event:
        coll = data.get("collection", "?")
        results = data.get("results", 0)
        scores = data.get("top_3_scores", [])
        dur = data.get("duration", "?")
        scores_str = ", ".join(scores[:3]) if scores else "none"
        return f"    {DIM}Qdrant: {coll} → {results} hits ({dur}) top=[{scores_str}]{RESET}"

    # ── Embedding ──
    if "[embedding]" in event and "cache" in event.lower():
        hit_miss = "HIT" if "HIT" in event else "MISS"
        color = GREEN if hit_miss == "HIT" else YELLOW
        return f"    {DIM}Embedding cache {color}{hit_miss}{RESET}"

    # ── Grok acknowledgment ──
    if "[grok]" in event:
        if "FAILED" in event:
            return f"  {YELLOW}⚠ Grok failed — using fallback{RESET}"
        return None

    # ── Errors ──
    if level == "warning":
        return f"  {YELLOW}⚠ {event.strip()}{RESET}"
    if level == "error":
        return f"  {RED}✗ {event.strip()}{RESET}"

    # ── Other detailed logs (indent = sub-operation) ──
    if event.startswith("  [") or event.startswith("    ["):
        return f"  {DIM}{event.strip()}{RESET}"

    # ── Startup/shutdown ──
    if "startup" in event.lower() or "Starting" in event:
        model = data.get("model", "")
        env = data.get("environment", "")
        if model:
            return f"  {CYAN}▶ Startup: env={env} model={model}{RESET}"
        return f"  {DIM}{event}{RESET}"

    # Skip circuit breaker noise and other verbose stuff
    if "circuit_breaker" in event:
        return None

    return None


def main():
    # Read from stdin (pipe) or file
    if len(sys.argv) > 1:
        source = open(sys.argv[1], "r", errors="replace")
    else:
        source = sys.stdin

    try:
        for line in source:
            formatted = format_line(line)
            if formatted is not None:
                print(formatted, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        if source is not sys.stdin:
            source.close()


if __name__ == "__main__":
    main()
