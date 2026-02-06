"""
FastAPI application entry point.

Starts the server and defines core routes.
"""

import asyncio
import json
import time

import psutil
import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sse_starlette.sse import EventSourceResponse

from src.agent.graph import stream_agent_response
from src.config import settings
from src.middleware.logging import TraceIdMiddleware, configure_structlog
from src.middleware.metrics import MetricsMiddleware, LoadMonitoringMiddleware
from src.models.api import ChatRequest, ChatResponse, HealthResponse, ServiceStatus
from src.monitoring.metrics import (
    ACTIVE_REQUESTS,
    ACTIVE_WORKERS,
    QUEUE_SIZE,
    QUEUE_UTILIZATION,
    MEMORY_USAGE,
    CPU_USAGE,
    ERRORS,
    WORKER_DURATION,
    REQUESTS_QUEUED,
    REQUESTS_REJECTED,
    USER_ABANDONED,
)
from src.services.cache import get_cache_service
from src.services.directus import get_directus_client
from src.services.errors import get_user_error, QueueFull, RateLimited
from src.services.qdrant import get_qdrant_service
from src.services.rate_limiter import get_rate_limiter
from src.monitoring.tracing import setup_tracing, instrument_fastapi
from src.monitoring.sentry import setup_sentry

# Configure structlog (replaces logging.basicConfig)
configure_structlog()
logger = structlog.get_logger()

# Initialize tracing and error tracking
setup_tracing()
setup_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup/shutdown tasks."""
    # Startup
    logger.info("Starting Erleah backend...")
    logger.info(
        "app.startup", environment=settings.environment, model=settings.anthropic_model
    )

    # Initialize Redis cache
    cache = get_cache_service()
    await cache.connect()

    # Cache warming: pre-warm system prompts into Anthropic cache by sending
    # a minimal request (the prompts get cached via cache_control: ephemeral)
    logger.info("cache.warming", status="started")
    # Prompts are cached on first LLM call via cache_control: ephemeral
    # No explicit warm-up needed — Anthropic prompt caching is automatic
    logger.info("cache.warming", status="done")

    # Start worker pool with configurable size
    app.state.request_queue = asyncio.Queue(maxsize=settings.max_queue_size)
    app.state.workers = [
        asyncio.create_task(_worker(i, app.state.request_queue))
        for i in range(settings.worker_pool_size)
    ]
    ACTIVE_WORKERS.set(settings.worker_pool_size)
    logger.info(
        "worker_pool.started",
        workers=settings.worker_pool_size,
        max_queue=settings.max_queue_size,
    )

    # Start resource monitor
    app.state.resource_monitor = asyncio.create_task(_resource_monitor())

    yield

    # Shutdown
    logger.info("Shutting down Erleah backend...")

    # Stop resource monitor
    app.state.resource_monitor.cancel()

    # Drain worker pool
    logger.info("worker_pool.draining")
    for _ in app.state.workers:
        await app.state.request_queue.put(None)  # Sentinel to stop workers

    # Wait for workers to finish (30s max)
    try:
        await asyncio.wait_for(
            asyncio.gather(*app.state.workers, return_exceptions=True),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "worker_pool.drain_timeout", remaining=app.state.request_queue.qsize()
        )
        for w in app.state.workers:
            w.cancel()

    await cache.close()


async def _worker(worker_id: int, queue: asyncio.Queue) -> None:
    """Worker coroutine: pull requests from queue and process them."""
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            break
        try:
            callback, message, user_context = item
            ACTIVE_REQUESTS.inc()
            start = time.perf_counter()
            try:
                async for event in stream_agent_response(message, user_context):
                    await callback(event)
            finally:
                ACTIVE_REQUESTS.dec()
                duration = time.perf_counter() - start
                WORKER_DURATION.observe(duration)
        except Exception as e:
            logger.error("worker.error", worker_id=worker_id, error=str(e))
            ERRORS.labels(error_type=type(e).__name__, node="worker").inc()
        finally:
            queue.task_done()
            QUEUE_SIZE.set(queue.qsize())
            QUEUE_UTILIZATION.set(queue.qsize() / settings.max_queue_size)


async def _resource_monitor() -> None:
    """Background task to track CPU and memory usage."""
    process = psutil.Process()
    while True:
        try:
            MEMORY_USAGE.set(process.memory_info().rss)
            CPU_USAGE.set(process.cpu_percent(interval=None))
        except Exception:
            pass
        await asyncio.sleep(10)


def _check_resources() -> bool:
    """Check if we have enough resources to accept new requests."""
    try:
        process = psutil.Process()
        cpu = process.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        if cpu > 80 or mem > 85:
            logger.warning("resource_throttle.triggered", cpu=cpu, memory=mem)
            return False
    except Exception:
        pass
    return True


# Create FastAPI app
app = FastAPI(
    title="Erleah Backend",
    description="AI-powered conference assistant with LangGraph",
    version="0.1.0",
    lifespan=lifespan,
)

# Middleware (order matters: last added = first executed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(MetricsMiddleware)
app.add_middleware(TraceIdMiddleware)

# Instrument with OpenTelemetry (if configured)
instrument_fastapi(app)


@app.get("/")
async def root():
    """Root endpoint - API info."""
    return {
        "name": "Erleah Backend",
        "version": "0.1.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health")
async def health_check():
    """Full health check endpoint with service connectivity."""
    return await _build_health_response()


@app.get("/health/ready")
async def readiness_check():
    """Kubernetes readiness probe. Returns 200 if all services connected."""
    response = await _build_health_response()
    if response.status == "healthy":
        return JSONResponse(content=response.model_dump(), status_code=200)
    return JSONResponse(content=response.model_dump(), status_code=503)


@app.get("/health/live")
async def liveness_check():
    """Kubernetes liveness probe. Returns 200 if process is alive."""
    return JSONResponse(content={"status": "alive"}, status_code=200)


async def _build_health_response() -> HealthResponse:
    """Build health response with service connectivity checks."""
    services: list[ServiceStatus] = []

    # Check Redis
    try:
        cache = get_cache_service()
        redis_ok = await cache.ping()
        services.append(
            ServiceStatus(name="redis", status="healthy" if redis_ok else "unhealthy")
        )
    except Exception:
        services.append(ServiceStatus(name="redis", status="unhealthy"))

    # Check Qdrant
    try:
        qdrant = get_qdrant_service()
        await qdrant.client.get_collections()
        services.append(ServiceStatus(name="qdrant", status="healthy"))
    except Exception:
        services.append(ServiceStatus(name="qdrant", status="unhealthy"))

    # Check Directus
    try:
        client = get_directus_client()
        resp = await client._client.get("/server/ping")
        services.append(
            ServiceStatus(
                name="directus",
                status="healthy" if resp.status_code == 200 else "unhealthy",
            )
        )
    except Exception:
        services.append(ServiceStatus(name="directus", status="unhealthy"))

    all_healthy = all(s.status == "healthy" for s in services)
    overall = "healthy" if all_healthy else "degraded"

    queue_size = 0
    if hasattr(app.state, "request_queue"):
        queue_size = app.state.request_queue.qsize()

    return HealthResponse(
        status=overall,
        environment=settings.environment,
        model=settings.anthropic_model,
        services=services,
        queue_size=queue_size,
        active_requests=int(ACTIVE_REQUESTS._value.get()),
    )


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return PlainTextResponse(
        content=generate_latest().decode("utf-8"),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """Stream agent responses via SSE.

    Routes requests through the worker queue for bounded concurrency.

    Response: Server-Sent Events stream with:
        - event: acknowledgment (contextual message from Grok)
        - event: progress (node started)
        - event: chunk (response tokens)
        - event: done (completion with trace_id + referenced_ids)
        - event: error (on failure)
    """
    rate_key = (
        request.user_context.user_id
        or request.user_context.conversation_id
        or "anonymous"
    )
    message = request.message
    user_context_dict = request.user_context.model_dump(exclude_none=True)

    logger.info(
        "========== SSE REQUEST ==========",
        endpoint="/api/chat/stream",
        message_preview=message[:120],
        user_id=request.user_context.user_id,
        conference_id=request.user_context.conference_id,
        conversation_id=request.user_context.conversation_id,
        rate_key=rate_key,
    )

    # Rate limiting
    limiter = get_rate_limiter()
    if not limiter.is_allowed(rate_key):
        logger.warning(
            "  [endpoint] RATE LIMITED — rejecting request",
            rate_key=rate_key,
        )
        error_info = get_user_error(RateLimited())
        return JSONResponse(status_code=429, content=error_info)
    logger.info("  [endpoint] rate limit check: PASSED", rate_key=rate_key)

    # Resource-based throttling
    if not _check_resources():
        logger.warning("  [endpoint] RESOURCE THROTTLE — rejecting request")
        return JSONResponse(
            status_code=503,
            content={
                "error": "Server under heavy load. Please try again shortly.",
                "can_retry": True,
            },
        )
    logger.info("  [endpoint] resource check: PASSED")

    # Check queue capacity
    queue = app.state.request_queue
    queue_current = queue.qsize()
    queue_max = settings.max_queue_size
    if queue.full():
        logger.warning(
            "  [endpoint] QUEUE FULL — rejecting request",
            queue_size=queue_current,
            max_queue=queue_max,
        )
        ERRORS.labels(error_type="QueueFull", node="endpoint").inc()
        REQUESTS_REJECTED.inc()
        error_info = get_user_error(QueueFull())
        return JSONResponse(
            status_code=503,
            content=error_info,
            headers={"Retry-After": "5"},
        )
    logger.info(
        "  [endpoint] queue check: PASSED",
        queue_size=queue_current,
        max_queue=queue_max,
    )

    REQUESTS_QUEUED.inc()

    async def event_generator():
        """Generate SSE events from agent stream."""
        ACTIVE_REQUESTS.inc()
        start = time.perf_counter()
        event_count = 0
        logger.info("  [sse_stream] starting event generator")
        try:
            async for event in stream_agent_response(message, user_context_dict):
                event_type = event.get("event", "message")
                event_data = event.get("data", {})
                event_count += 1

                yield {
                    "event": event_type,
                    "data": json.dumps(event_data),
                }
        except asyncio.CancelledError:
            # Client disconnected
            elapsed = time.perf_counter() - start
            logger.warning(
                "  [sse_stream] CLIENT DISCONNECTED",
                events_sent=event_count,
                elapsed=f"{elapsed:.2f}s",
            )
            USER_ABANDONED.inc()
            raise
        finally:
            ACTIVE_REQUESTS.dec()
            duration = time.perf_counter() - start
            WORKER_DURATION.observe(duration)
            logger.info(
                "  [sse_stream] event generator finished",
                events_sent=event_count,
                total_duration=f"{duration:.2f}s",
            )

    QUEUE_SIZE.set(queue.qsize())
    QUEUE_UTILIZATION.set(queue.qsize() / settings.max_queue_size)

    logger.info("  [endpoint] starting SSE response stream")
    return EventSourceResponse(event_generator())


@app.post("/api/chat")
async def chat_non_streaming(request: ChatRequest):
    """Non-streaming chat endpoint (for testing).

    Response:
        {
            "response": "I found 5 Python developers...",
            "events": [...]
        }
    """
    rate_key = (
        request.user_context.user_id
        or request.user_context.conversation_id
        or "anonymous"
    )

    logger.info(
        "========== NON-STREAMING REQUEST ==========",
        endpoint="/api/chat",
        message_preview=request.message[:120],
        user_id=request.user_context.user_id,
        conference_id=request.user_context.conference_id,
        rate_key=rate_key,
    )

    # Rate limiting
    limiter = get_rate_limiter()
    if not limiter.is_allowed(rate_key):
        logger.warning("  [endpoint] RATE LIMITED", rate_key=rate_key)
        error_info = get_user_error(RateLimited())
        return JSONResponse(status_code=429, content=error_info)

    message = request.message
    user_context = request.user_context.model_dump(exclude_none=True)

    # Collect all events
    events = []
    response_text = ""
    start = time.perf_counter()

    async for event in stream_agent_response(message, user_context):
        events.append(event)

        if event["event"] == "chunk":
            response_text += event["data"].get("text", "")

    duration = time.perf_counter() - start
    logger.info(
        "  [endpoint] non-streaming response complete",
        events_count=len(events),
        response_length=len(response_text),
        duration=f"{duration:.2f}s",
    )

    return ChatResponse(
        response=response_text.strip(),
        events=events,
    )
    limiter = get_rate_limiter()
    if not limiter.is_allowed(rate_key):
        error_info = get_user_error(RateLimited())
        return JSONResponse(status_code=429, content=error_info)

    message = request.message
    user_context = request.user_context.model_dump(exclude_none=True)

    # Collect all events
    events = []
    response_text = ""

    async for event in stream_agent_response(message, user_context):
        events.append(event)

        if event["event"] == "chunk":
            response_text += event["data"].get("text", "")

    return ChatResponse(
        response=response_text.strip(),
        events=events,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.api_reload,
    )
