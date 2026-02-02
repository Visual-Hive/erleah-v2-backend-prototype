"""Prometheus metrics definitions."""

from prometheus_client import Counter, Gauge, Histogram

# Request metrics
REQUEST_COUNT = Counter(
    "assistant_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_DURATION = Histogram(
    "assistant_request_duration_seconds",
    "HTTP request duration in seconds",
    ["endpoint"],
    buckets=[1, 2, 3, 5, 7, 10, 15, 20, 30],
)

# Cache metrics
CACHE_HIT = Counter(
    "assistant_cache_hits_total",
    "Total cache hits",
    ["cache_type"],
)

CACHE_MISS = Counter(
    "assistant_cache_misses_total",
    "Total cache misses",
    ["cache_type"],
)

CACHE_OPERATION_DURATION = Histogram(
    "assistant_cache_operation_duration_seconds",
    "Cache operation duration in seconds",
    ["operation"],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
)

# LLM metrics
LLM_CALLS = Counter(
    "assistant_llm_calls_total",
    "Total LLM API calls",
    ["model", "node"],
)

LLM_TOKENS = Counter(
    "assistant_llm_tokens_total",
    "Total LLM tokens used",
    ["model", "token_type"],  # token_type: input, output, cached
)

LLM_DURATION = Histogram(
    "assistant_llm_duration_seconds",
    "LLM call duration in seconds",
    ["model"],
    buckets=[0.5, 1, 2, 3, 5, 8, 10],
)

# Search quality metrics
SEARCH_RESULTS = Histogram(
    "assistant_search_results",
    "Number of search results returned",
    ["table", "mode"],
    buckets=[0, 1, 2, 5, 10, 20, 50],
)

FACETED_SEARCH_SCORE = Histogram(
    "assistant_faceted_search_score",
    "Faceted search composite scores",
    buckets=[0, 2, 4, 6, 8, 9, 10],
)

FACETED_SEARCH_DURATION = Histogram(
    "assistant_faceted_search_duration_seconds",
    "Faceted search execution duration",
    ["entity_type"],
    buckets=[0.1, 0.25, 0.5, 1, 2, 5],
)

FACETS_MATCHED = Histogram(
    "assistant_facets_matched",
    "Number of facets matched per search",
    buckets=[0, 1, 2, 3, 4, 5, 6, 7, 8],
)

FACET_PAIR_SIMILARITY = Histogram(
    "assistant_facet_pair_similarity",
    "Similarity scores for paired facet matching",
    ["facet_key"],
    buckets=[0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0],
)

# Error metrics
ERRORS = Counter(
    "assistant_errors_total",
    "Total errors",
    ["error_type", "node"],
)

# Concurrency metrics
QUEUE_SIZE = Gauge(
    "assistant_queue_size",
    "Current queue size",
)

QUEUE_UTILIZATION = Gauge(
    "assistant_queue_utilization",
    "Queue utilization ratio (0-1)",
)

ACTIVE_WORKERS = Gauge(
    "assistant_active_workers",
    "Number of active workers",
)

ACTIVE_REQUESTS = Gauge(
    "assistant_active_requests",
    "Currently active requests",
)

WORKER_DURATION = Histogram(
    "assistant_worker_duration_seconds",
    "Time workers spend processing requests",
    buckets=[1, 2, 5, 7, 10, 15, 20, 30],
)

REQUESTS_QUEUED = Counter(
    "assistant_requests_queued_total",
    "Total requests queued",
)

REQUESTS_REJECTED = Counter(
    "assistant_requests_rejected_total",
    "Total requests rejected (queue full)",
)

# UX timing metrics
TIME_TO_FIRST_FEEDBACK = Histogram(
    "assistant_time_to_first_feedback_seconds",
    "Time from request to first SSE event",
    buckets=[0.5, 1, 2, 3, 5, 8, 10],
)

TIME_TO_FIRST_CHUNK = Histogram(
    "assistant_time_to_first_chunk_seconds",
    "Time from request to first response chunk",
    buckets=[2, 3, 4, 5, 6, 8, 10, 15],
)

# User experience metrics
USER_ABANDONED = Counter(
    "assistant_user_abandoned_total",
    "Total user abandoned requests (disconnected before done)",
)

USER_SATISFACTION = Histogram(
    "assistant_user_satisfaction",
    "User satisfaction scores from evaluation",
    buckets=[0, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0],
)

# System metrics
MEMORY_USAGE = Gauge(
    "assistant_memory_bytes",
    "Process memory usage in bytes",
)

CPU_USAGE = Gauge(
    "assistant_cpu_percent",
    "Process CPU usage percentage",
)
