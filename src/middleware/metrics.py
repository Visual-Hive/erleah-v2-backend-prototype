"""Prometheus metrics middleware."""

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.monitoring.metrics import REQUEST_DURATION, REQUESTS_TOTAL


class MetricsMiddleware(BaseHTTPMiddleware):
    """Time requests and increment Prometheus counters."""

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response: Response = await call_next(request)
        duration = time.perf_counter() - start

        endpoint = request.url.path
        REQUESTS_TOTAL.labels(
            method=request.method,
            endpoint=endpoint,
            status=response.status_code,
        ).inc()
        REQUEST_DURATION.labels(endpoint=endpoint).observe(duration)

        return response
