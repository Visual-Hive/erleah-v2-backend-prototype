"""Prometheus metrics definitions."""

from prometheus_client import Counter, Gauge, Histogram

# Request metrics
REQUESTS_TOTAL = Counter(
    "erleah_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_DURATION = Histogram(
    "erleah_request_duration_seconds",
    "HTTP request duration in seconds",
    ["endpoint"],
)

# Cache metrics
CACHE_HITS = Counter(
    "erleah_cache_hits_total",
    "Total cache hits",
    ["layer"],
)

CACHE_MISSES = Counter(
    "erleah_cache_misses_total",
    "Total cache misses",
    ["layer"],
)

# LLM metrics
LLM_CALLS = Counter(
    "erleah_llm_calls_total",
    "Total LLM API calls",
    ["model", "node"],
)

# Concurrency metrics
QUEUE_SIZE = Gauge(
    "erleah_queue_size",
    "Current queue size",
)

ACTIVE_REQUESTS = Gauge(
    "erleah_active_requests",
    "Currently active requests",
)
