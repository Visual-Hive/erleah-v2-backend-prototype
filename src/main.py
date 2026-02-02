"""
FastAPI application entry point.

Starts the server and defines core routes.
"""

import asyncio
import json

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
from src.middleware.metrics import MetricsMiddleware
from src.models.api import ChatRequest, ChatResponse, HealthResponse, ServiceStatus
from src.monitoring.metrics import ACTIVE_REQUESTS
from src.services.cache import get_cache_service
from src.services.directus import get_directus_client
from src.services.qdrant import get_qdrant_service

# Configure structlog (replaces logging.basicConfig)
configure_structlog()
logger = structlog.get_logger()

# Concurrency semaphore
_semaphore = asyncio.Semaphore(20)
_active_requests = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup/shutdown tasks."""
    # Startup
    logger.info("Starting Erleah backend...")
    logger.info("app.startup", environment=settings.environment, model=settings.anthropic_model)

    # Initialize Redis cache
    cache = get_cache_service()
    await cache.connect()

    yield

    # Shutdown
    logger.info("Shutting down Erleah backend...")
    await cache.close()


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
    """Health check endpoint with service connectivity."""
    global _active_requests
    services: list[ServiceStatus] = []

    # Check Redis
    try:
        cache = get_cache_service()
        redis_ok = await cache.ping()
        services.append(ServiceStatus(name="redis", status="healthy" if redis_ok else "unhealthy"))
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
        services.append(ServiceStatus(name="directus", status="healthy" if resp.status_code == 200 else "unhealthy"))
    except Exception:
        services.append(ServiceStatus(name="directus", status="unhealthy"))

    all_healthy = all(s.status == "healthy" for s in services)
    overall = "healthy" if all_healthy else "degraded"

    return HealthResponse(
        status=overall,
        environment=settings.environment,
        model=settings.anthropic_model,
        services=services,
        active_requests=_active_requests,
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

    Response: Server-Sent Events stream with:
        - event: acknowledgment (request received + contextual message)
        - event: progress (node started)
        - event: chunk (response tokens)
        - event: done (completion)
        - event: error (on failure)
    """
    global _active_requests

    # Check concurrency
    if _semaphore.locked() and _semaphore._value == 0:
        return JSONResponse(
            status_code=503,
            content={"error": "Server at capacity. Please try again shortly."},
        )

    message = request.message
    user_context = request.user_context.model_dump(exclude_none=True)

    async def event_generator():
        """Generate SSE events from agent stream."""
        global _active_requests
        async with _semaphore:
            _active_requests += 1
            ACTIVE_REQUESTS.set(_active_requests)
            try:
                async for event in stream_agent_response(message, user_context):
                    event_type = event.get("event", "message")
                    event_data = event.get("data", {})

                    yield {
                        "event": event_type,
                        "data": json.dumps(event_data),
                    }

            except Exception as e:
                logger.error("agent_stream.error", error=str(e), exc_info=True)
                yield {
                    "event": "error",
                    "data": json.dumps({"error": str(e)}),
                }
            finally:
                _active_requests -= 1
                ACTIVE_REQUESTS.set(_active_requests)

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
    message = request.message
    user_context = request.user_context.model_dump(exclude_none=True)

    # Collect all events
    events = []
    response_text = ""

    async for event in stream_agent_response(message, user_context):
        events.append(event)

        if event["event"] == "chunk":
            response_text += event["data"].get("token", "")

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
