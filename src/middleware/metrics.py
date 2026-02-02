"""Prometheus metrics middleware with load monitoring."""

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.monitoring.metrics import (
    REQUEST_COUNT, REQUEST_DURATION,
    QUEUE_SIZE, QUEUE_UTILIZATION, ACTIVE_WORKERS,
)

logger = structlog.get_logger()


class MetricsMiddleware(BaseHTTPMiddleware):
    """Time requests and increment Prometheus counters."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response: Response = await call_next(request)
        duration = time.perf_counter() - start

        endpoint = request.url.path
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=endpoint,
            status=response.status_code,
        ).inc()
        REQUEST_DURATION.labels(endpoint=endpoint).observe(duration)

        return response


class LoadMonitoringMiddleware(BaseHTTPMiddleware):
    """Monitor load levels and log warnings at high utilization."""

    def __init__(self, app, request_queue=None, max_queue_size: int = 100):
        super().__init__(app)
        self._request_queue = request_queue
        self._max_queue_size = max_queue_size

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._request_queue is not None:
            queue_size = self._request_queue.qsize()
            utilization = queue_size / self._max_queue_size if self._max_queue_size > 0 else 0

            QUEUE_SIZE.set(queue_size)
            QUEUE_UTILIZATION.set(utilization)

            # Log warnings at high utilization levels
            if utilization > 0.95:
                logger.warning(
                    "load.critical",
                    queue_size=queue_size,
                    utilization=f"{utilization:.1%}",
                    level="critical",
                )
            elif utilization > 0.8:
                logger.warning(
                    "load.high",
                    queue_size=queue_size,
                    utilization=f"{utilization:.1%}",
                    level="warning",
                )

        response = await call_next(request)
        return response
