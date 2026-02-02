"""Sentry error tracking setup."""

import structlog

from src.config import settings

logger = structlog.get_logger()


def setup_sentry() -> None:
    """Initialize Sentry if DSN is configured."""
    if not settings.sentry_dsn:
        logger.info("sentry.skip", reason="SENTRY_DSN not set")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            integrations=[
                StarletteIntegration(),
                FastApiIntegration(),
            ],
            send_default_pii=False,
        )

        logger.info("sentry.initialized", environment=settings.environment)
    except ImportError:
        logger.warning("sentry.import_error", message="sentry-sdk not installed")
    except Exception as e:
        logger.warning("sentry.setup_failed", error=str(e))
