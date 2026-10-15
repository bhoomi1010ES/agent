"""Unit tests for application lifecycle, middleware configurations, and factory options."""

import pytest
from httpx import ASGITransport, AsyncClient

from modernization_platform.app import create_app, lifespan
from modernization_platform.config.settings import Settings


@pytest.mark.asyncio
async def test_application_lifespan_context() -> None:
    """Verify application lifespan startup and shutdown hooks execute cleanly."""
    settings = Settings(environment="test", debug=True)
    app = create_app(settings=settings)

    async with lifespan(app):
        # Application is active and running within lifespan context
        assert app.state.settings.environment == "test"


@pytest.mark.asyncio
async def test_app_with_docs_disabled() -> None:
    """Verify OpenAPI and Swagger docs routes are disabled when docs_enabled is False."""
    settings = Settings(environment="test", docs_enabled=False)
    app = create_app(settings=settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        docs_res = await client.get("/docs")
        assert docs_res.status_code == 404

        openapi_res = await client.get("/openapi.json")
        assert openapi_res.status_code == 404


@pytest.mark.asyncio
async def test_app_with_trusted_hosts() -> None:
    """Verify TrustedHostMiddleware enforces allowed host headers."""
    settings = Settings(
        environment="test",
        allowed_hosts=["allowed.modernizer.local"],
        cors_allowed_origins=["http://allowed.modernizer.local"],
    )
    app = create_app(settings=settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://allowed.modernizer.local"
    ) as client:
        # Valid host header
        valid_res = await client.get("/health/live", headers={"Host": "allowed.modernizer.local"})
        assert valid_res.status_code == 200

        # Invalid host header
        invalid_res = await client.get("/health/live", headers={"Host": "evil.attacker.com"})
        assert invalid_res.status_code == 400


@pytest.mark.asyncio
async def test_starlette_http_exception_handling() -> None:
    """Verify method not allowed (405) is formatted as standardized error JSON."""
    settings = Settings(environment="test")
    app = create_app(settings=settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # POST to GET-only endpoint returns 405
        res = await client.post("/health/live")
        assert res.status_code == 405
        data = res.json()
        assert data["code"] == "METHOD_NOT_ALLOWED"
        assert "request_id" in data
