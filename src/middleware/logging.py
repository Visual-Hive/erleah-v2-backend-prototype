"""Structlog configuration and trace ID middleware."""

import uuid
from contextvars import ContextVar

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def configure_structlog() -> None:
    """Configure structlog with JSON rendering and contextvars."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Extract or generate X-Trace-ID, bind to structlog context."""

    async def dispatch(self, request: Request, call_next) -> Response:
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
        trace_id_var.set(trace_id)
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)

        response: Response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response
