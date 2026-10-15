"""FastAPI application factory and lifecycle management."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from modernization_platform.api.root import router as root_router
from modernization_platform.api.v1.endpoints.health import (
    ReadinessProbeResult,
    readiness_registry,
)
from modernization_platform.api.v1.endpoints.health import (
    router as health_router,
)
from modernization_platform.api.v1.router import api_v1_router
from modernization_platform.config.settings import Settings, get_settings
from modernization_platform.core.logging import setup_logging
from modernization_platform.core.middleware import (
    CorrelationIdMiddleware,
    RequestBodyLimitMiddleware,
    register_exception_handlers,
)
from modernization_platform.db.engine import (
    check_database_readiness,
    dispose_database_engine,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan context manager for startup and shutdown hooks."""
    current_settings: Settings = getattr(app.state, "settings", get_settings())
    try:
        logger.info(
            "Starting %s v%s in '%s' environment (debug=%s)",
            current_settings.app_name,
            current_settings.app_version,
            current_settings.environment,
            current_settings.debug,
        )

        # Register bounded database readiness probe when database is configured
        if current_settings.environment != "test" and current_settings.database_url:

            async def _db_probe() -> ReadinessProbeResult:
                try:
                    is_ready, msg = await check_database_readiness(
                        timeout_seconds=current_settings.health_check_timeout_seconds
                    )
                    return ReadinessProbeResult(ready=is_ready, message=msg)
                except Exception as exc:
                    logger.exception(
                        "Database probe encountered unexpected error | %s: %s",
                        type(exc).__name__,
                        exc,
                    )
                    return ReadinessProbeResult(
                        ready=False, message="Database connectivity check failed"
                    )

            readiness_registry.register_probe("database", _db_probe)

        yield
    except Exception as exc:
        logger.exception("Fatal error during application startup | %s: %s", type(exc).__name__, exc)
        raise
    finally:
        try:
            logger.info("Initiating graceful shutdown for %s", current_settings.app_name)
            readiness_registry._probes.pop("database", None)
            await dispose_database_engine()
        except Exception as exc:
            logger.exception("Error during application shutdown | %s: %s", type(exc).__name__, exc)


def create_app(settings: Settings | None = None) -> FastAPI:
    """FastAPI application factory.

    Constructs and configures the FastAPI application instance with lifecycle hooks,
    security middleware, centralized exception handling, and routing.
    """
    app_settings = settings or get_settings()

    try:
        # Initialize structured logging
        setup_logging(app_settings)

        # Configure interactive documentation exposure based on settings
        docs_url = "/docs" if app_settings.docs_enabled else None
        redoc_url = "/redoc" if app_settings.docs_enabled else None
        openapi_url = "/openapi.json" if app_settings.docs_enabled else None

        app = FastAPI(
            title=app_settings.app_name,
            version=app_settings.app_version,
            description="Multi-Agent Legacy Code Modernization Platform - Control Plane API",
            docs_url=docs_url,
            redoc_url=redoc_url,
            openapi_url=openapi_url,
            lifespan=lifespan,
        )

        # Attach settings to application state and configure dependency override
        app.state.settings = app_settings
        app.dependency_overrides[get_settings] = lambda: app_settings

        # 1. Register centralized exception handlers
        register_exception_handlers(app)

        # 2. Add Correlation ID middleware
        app.add_middleware(
            CorrelationIdMiddleware,
            header_name=app_settings.correlation_header_name,
        )

        # 3. Bound request bodies before Pydantic parsing and protected operations.
        app.add_middleware(
            RequestBodyLimitMiddleware,
            max_body_bytes=app_settings.max_request_body_bytes,
        )

        # 4. Add CORS middleware
        if app_settings.cors_allowed_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=app_settings.cors_allowed_origins,
                allow_credentials=app_settings.cors_allow_credentials,
                allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                allow_headers=["*"],
                expose_headers=[app_settings.correlation_header_name],
            )

        # 5. Add Trusted Host middleware if configured
        if app_settings.allowed_hosts and "*" not in app_settings.allowed_hosts:
            app.add_middleware(
                TrustedHostMiddleware,
                allowed_hosts=app_settings.allowed_hosts,
            )

        # 6. Mount API routes
        # Mount top-level root endpoint (GET /)
        app.include_router(root_router)

        # Mount top-level /health endpoints (e.g. /health/live, /health/ready for orchestrators/k8s)
        app.include_router(health_router, prefix="/health", tags=["Health"])

        # Mount versioned API routes (/api/v1)
        app.include_router(api_v1_router, prefix=app_settings.api_v1_prefix)

        logger.debug("FastAPI application instance created successfully.")
        return app
    except Exception as exc:
        logger.exception("create_app factory failed | %s: %s", type(exc).__name__, exc)
        raise
