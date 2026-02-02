"""OpenTelemetry distributed tracing setup."""

import structlog

from src.config import settings

logger = structlog.get_logger()


def setup_tracing() -> None:
    """Initialize OpenTelemetry tracing if endpoint is configured."""
    if not settings.otel_exporter_endpoint:
        logger.info("tracing.skip", reason="OTEL_EXPORTER_ENDPOINT not set")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        resource = Resource.create({
            "service.name": settings.otel_service_name,
            "service.version": "0.1.0",
            "deployment.environment": settings.environment,
        })

        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        logger.info("tracing.initialized", endpoint=settings.otel_exporter_endpoint)
    except ImportError:
        logger.warning("tracing.import_error", message="opentelemetry packages not installed")
    except Exception as e:
        logger.warning("tracing.setup_failed", error=str(e))


def instrument_fastapi(app) -> None:
    """Instrument FastAPI app with OpenTelemetry."""
    if not settings.otel_exporter_endpoint:
        return

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app)
        logger.info("tracing.fastapi_instrumented")
    except ImportError:
        pass
    except Exception as e:
        logger.warning("tracing.fastapi_instrument_failed", error=str(e))
