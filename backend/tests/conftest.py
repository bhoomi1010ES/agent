from collections.abc import AsyncIterator, Iterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from modernization_platform.app import create_app
from modernization_platform.config.settings import Settings

pytest_plugins = ["tests.integration.db.conftest"]


@pytest.fixture
def test_settings() -> Settings:
    """Provide isolated settings tailored for unit and integration testing."""
    return Settings(
        app_name="ModernizationPlatformTest",
        app_version="0.1.0-test",
        environment="test",
        debug=True,
        host="127.0.0.1",
        port=8000,
        api_v1_prefix="/api/v1",
        allowed_hosts=["*"],
        cors_allowed_origins=["http://testserver"],
        cors_allow_credentials=True,
        docs_enabled=True,
        log_level="DEBUG",
        log_format="console",
        correlation_header_name="X-Correlation-ID",
        health_check_timeout_seconds=2.0,
    )


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    """Instantiate FastAPI application using test configuration."""
    return create_app(settings=test_settings)


@pytest.fixture
async def async_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Provide an asynchronous HTTPX test client bound to the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture(autouse=True)
def _clean_default_pricing_registry() -> Iterator[None]:
    """Ensure global default_pricing_registry is never polluted across test cases."""
    from modernization_platform.domain.model_gateway.pricing import default_pricing_registry

    yield
    default_pricing_registry.reset()
