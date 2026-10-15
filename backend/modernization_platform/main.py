"""Minimal ASGI application entry point."""

import logging

from modernization_platform.app import create_app
from modernization_platform.config.settings import get_settings

logger = logging.getLogger(__name__)

# Default ASGI callable
app = create_app()

if __name__ == "__main__":
    try:
        import uvicorn

        settings = get_settings()
        uvicorn.run(
            "modernization_platform.main:app",
            host=settings.host,
            port=settings.port,
            reload=settings.debug,
            log_config=None,  # Handled by modernization_platform.core.logging
        )
    except Exception as exc:
        logger.exception(
            "Failed to start application via main.py | %s: %s", type(exc).__name__, exc
        )
        raise
