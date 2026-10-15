"""Integration tests for request correlation ID extraction, validation, and propagation."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_request_generates_correlation_id_if_missing(async_client: AsyncClient) -> None:
    """Verify response contains an X-Correlation-ID header when client provides none."""
    response = await async_client.get("/health/live")
    assert response.status_code == 200
    assert "X-Correlation-ID" in response.headers
    cid = response.headers["X-Correlation-ID"]
    assert len(cid) >= 16


@pytest.mark.asyncio
async def test_valid_incoming_correlation_id_is_preserved(async_client: AsyncClient) -> None:
    """Verify client-supplied valid correlation ID is accepted and echoed in the response."""
    custom_id = "req-client-trace-12345"
    response = await async_client.get("/health/live", headers={"X-Correlation-ID": custom_id})
    assert response.status_code == 200
    assert response.headers.get("X-Correlation-ID") == custom_id


@pytest.mark.asyncio
async def test_invalid_correlation_id_is_sanitized_and_regenerated(
    async_client: AsyncClient,
) -> None:
    """Verify malformed or oversized correlation IDs are safely discarded and replaced with a UUID."""
    # Header with invalid characters (potential header injection or script injection attempt)
    malicious_id = "bad\r\nid\x00<script>alert(1)</script>"
    response = await async_client.get("/health/live", headers={"X-Correlation-ID": malicious_id})
    assert response.status_code == 200
    cid = response.headers.get("X-Correlation-ID")
    assert cid is not None
    assert cid != malicious_id
    assert "<script>" not in cid

    # Oversized header (> 64 characters)
    oversized_id = "a" * 128
    res_oversized = await async_client.get(
        "/health/live", headers={"X-Correlation-ID": oversized_id}
    )
    assert res_oversized.status_code == 200
    cid_oversized = res_oversized.headers.get("X-Correlation-ID")
    assert cid_oversized is not None
    assert cid_oversized != oversized_id
    assert len(cid_oversized) <= 64
