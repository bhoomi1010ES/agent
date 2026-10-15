"""Integration tests for application liveness and readiness health endpoints."""

import pytest
from httpx import AsyncClient

from modernization_platform.api.v1.endpoints.health import (
    ReadinessProbeResult,
    readiness_registry,
)


@pytest.mark.asyncio
async def test_liveness_endpoint(async_client: AsyncClient) -> None:
    """Verify GET /health/live returns HTTP 200 with process health data."""
    response = await async_client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"
    assert "timestamp" in data
    assert data["version"] == "0.1.0-test"


@pytest.mark.asyncio
async def test_readiness_endpoint_baseline(async_client: AsyncClient) -> None:
    """Verify GET /health/ready returns HTTP 200 when all probes pass (baseline)."""
    response = await async_client.get("/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "timestamp" in data
    assert isinstance(data["probes"], dict)


@pytest.mark.asyncio
async def test_versioned_health_endpoints(async_client: AsyncClient) -> None:
    """Verify /api/v1/health routes are also accessible and identical."""
    live_res = await async_client.get("/api/v1/health/live")
    assert live_res.status_code == 200
    assert live_res.json()["status"] == "alive"

    ready_res = await async_client.get("/api/v1/health/ready")
    assert ready_res.status_code == 200
    assert ready_res.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_readiness_probe_failure_returns_503(async_client: AsyncClient) -> None:
    """Verify that a failing registered probe causes /health/ready to return HTTP 503."""

    async def mock_failing_probe() -> ReadinessProbeResult:
        return ReadinessProbeResult(ready=False, message="Simulated downstream dependency failure")

    readiness_registry.register_probe("mock_db", mock_failing_probe)

    try:
        response = await async_client.get("/health/ready")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert "mock_db" in data["probes"]
        assert data["probes"]["mock_db"]["ready"] is False
        assert "Simulated downstream dependency failure" in data["probes"]["mock_db"]["message"]
    finally:
        # Clean up mock probe from registry
        readiness_registry._probes.pop("mock_db", None)


@pytest.mark.asyncio
async def test_readiness_probe_timeout(async_client: AsyncClient) -> None:
    """Verify probe timeout is caught and reported safely."""
    import asyncio

    async def mock_slow_probe() -> ReadinessProbeResult:
        await asyncio.sleep(0.5)
        return ReadinessProbeResult(ready=True)

    readiness_registry.register_probe("slow_service", mock_slow_probe)

    try:
        # Run with tiny timeout
        is_ready, results = await readiness_registry.run_all(timeout_seconds=0.01)
        assert is_ready is False
        assert results["slow_service"].ready is False
        assert "timed out" in (results["slow_service"].message or "")
    finally:
        readiness_registry._probes.pop("slow_service", None)


@pytest.mark.asyncio
async def test_readiness_probe_exception_handled() -> None:
    """Verify probe raising uncaught exception is handled and does not crash registry."""

    async def mock_crash_probe() -> ReadinessProbeResult:
        raise ConnectionResetError("Socket reset by peer")

    readiness_registry.register_probe("crashed_conn", mock_crash_probe)

    try:
        is_ready, results = await readiness_registry.run_all(timeout_seconds=1.0)
        assert is_ready is False
        assert results["crashed_conn"].ready is False
        assert "error" in (results["crashed_conn"].message or "")
    finally:
        readiness_registry._probes.pop("crashed_conn", None)
