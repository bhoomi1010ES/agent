"""Integration tests for the GET / root endpoint."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from modernization_platform.api.root import RootResponse
from modernization_platform.app import create_app
from modernization_platform.config.settings import Settings


@pytest.mark.asyncio
async def test_root_endpoint_default(async_client: AsyncClient, test_settings: Settings) -> None:
    """Verify GET / returns HTTP 200 with application name, version, running status, and docs path."""
    response = await async_client.get("/")
    assert response.status_code == 200

    data = response.json()
    # Validate against Pydantic schema
    validated = RootResponse(**data)

    assert validated.app_name == test_settings.app_name
    assert validated.name == test_settings.app_name
    assert validated.version == test_settings.app_version
    assert validated.status == "running"
    assert validated.docs_url == "/docs"
    assert validated.docs == "/docs"


@pytest.mark.asyncio
async def test_root_endpoint_docs_disabled(test_settings: Settings) -> None:
    """Verify GET / returns None for docs_url when docs_enabled is False."""
    custom_settings = test_settings.model_copy(update={"docs_enabled": False})
    custom_app = create_app(settings=custom_settings)

    transport = ASGITransport(app=custom_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["docs_url"] is None
        assert data["docs"] is None
        assert data["status"] == "running"
        assert data["app_name"] == test_settings.app_name


@pytest.mark.asyncio
async def test_root_endpoint_custom_configuration(test_settings: Settings) -> None:
    """Verify GET / dynamically reflects configured application name and version."""
    custom_settings = test_settings.model_copy(
        update={
            "app_name": "LegacyModernizerPro",
            "app_version": "1.5.0-beta",
        }
    )
    custom_app = create_app(settings=custom_settings)

    transport = ASGITransport(app=custom_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["app_name"] == "LegacyModernizerPro"
        assert data["name"] == "LegacyModernizerPro"
        assert data["version"] == "1.5.0-beta"
        assert data["status"] == "running"
        assert data["docs_url"] == "/docs"


@pytest.mark.asyncio
async def test_root_endpoint_error_handling(async_client: AsyncClient) -> None:
    """Verify that unexpected exceptions in get_root are logged and result in HTTP 500."""
    with patch(
        "modernization_platform.api.root.RootResponse",
        side_effect=RuntimeError("Simulated internal error in root schema construction"),
    ):
        response = await async_client.get("/")
        assert response.status_code == 500
        error_payload = response.json()
        assert error_payload["code"] == "INTERNAL_SERVER_ERROR"
