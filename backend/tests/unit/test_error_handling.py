"""Unit tests for standardized error handling and exception hierarchy."""

import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from modernization_platform.core.exceptions import (
    BadRequestException,
    ForbiddenException,
    NotFoundException,
    UnauthorizedException,
)
from modernization_platform.core.middleware import (
    CorrelationIdMiddleware,
    application_exception_handler,
    create_error_response,
    http_exception_handler,
    register_exception_handlers,
    unhandled_exception_handler,
)


class SamplePayload(BaseModel):
    name: str = Field(min_length=3)
    count: int = Field(gt=0)


@pytest.fixture
def error_test_app() -> FastAPI:
    """Create a minimal app with routes that raise specific exceptions."""
    test_app = FastAPI()
    register_exception_handlers(test_app)
    test_app.add_middleware(CorrelationIdMiddleware)

    @test_app.get("/test-not-found")
    async def route_not_found() -> None:
        raise NotFoundException(message="Item 123 was not found", details={"item_id": 123})

    @test_app.get("/test-bad-request")
    async def route_bad_request() -> None:
        raise BadRequestException(message="Malformed request parameter")

    @test_app.get("/test-unauthorized")
    async def route_unauthorized() -> None:
        raise UnauthorizedException(message="Token expired")

    @test_app.get("/test-forbidden")
    async def route_forbidden() -> None:
        raise ForbiddenException(message="User lacks approval permissions")

    @test_app.post("/test-validation")
    async def route_validation(payload: SamplePayload) -> dict[str, str]:
        return {"received": payload.name}

    @test_app.get("/test-unhandled-crash")
    async def route_unhandled_crash() -> None:
        # Raise unexpected internal error
        raise RuntimeError(
            "Database connection string postgresql://user:secret@db:5432 failed /var/secrets/key.pem"
        )

    return test_app


@pytest.mark.asyncio
async def test_not_found_exception_handling(error_test_app: FastAPI) -> None:
    """Verify NotFoundException produces standardized 404 response."""
    transport = ASGITransport(app=error_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test-not-found")
        assert response.status_code == 404
        data = response.json()
        assert data["code"] == "NOT_FOUND"
        assert data["message"] == "Item 123 was not found"
        assert data["details"] == {"item_id": 123}
        assert "request_id" in data
        assert len(data["request_id"]) > 0


@pytest.mark.asyncio
async def test_validation_exception_handling(error_test_app: FastAPI) -> None:
    """Verify invalid request body returns safe RFC 9457 structured 422 error."""
    transport = ASGITransport(app=error_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/test-validation", json={"name": "a", "count": -5})
        assert response.status_code == 422
        data = response.json()
        assert data["code"] == "VALIDATION_ERROR"
        assert "request input validation failed" in data["message"].lower()
        assert isinstance(data["details"], list)
        assert len(data["details"]) >= 2
        assert "request_id" in data


@pytest.mark.asyncio
async def test_unhandled_exception_redaction(error_test_app: FastAPI) -> None:
    """Verify unexpected internal exception returns generic 500 without leaking sensitive text or stack trace."""
    transport = ASGITransport(app=error_test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test-unhandled-crash")
        assert response.status_code == 500
        data = response.json()
        assert data["code"] == "INTERNAL_SERVER_ERROR"
        # Must NOT expose credentials, paths, or exception text
        assert "postgresql" not in response.text
        assert "secret" not in response.text
        assert "key.pem" not in response.text
        assert "RuntimeError" not in response.text
        assert "request_id" in data
        assert len(data["request_id"]) > 0


@pytest.mark.asyncio
async def test_create_error_response_direct() -> None:
    """Verify create_error_response generates standardized JSON response."""
    res = create_error_response(
        status_code=400,
        code="TEST_ERROR",
        message="A test error message",
        details={"field": "value"},
    )
    assert res.status_code == 400

    body = json.loads(bytes(res.body).decode("utf-8"))
    assert body["code"] == "TEST_ERROR"
    assert body["message"] == "A test error message"
    assert body["details"] == {"field": "value"}
    assert "request_id" in body

    # Test direct application_exception_handler call
    scope = {"type": "http", "method": "GET", "path": "/test", "headers": []}
    mock_request = Request(scope)
    app_exc = NotFoundException(message="Direct not found", details={"id": 999})
    handler_res = await application_exception_handler(mock_request, app_exc)
    assert handler_res.status_code == 404
    h_body = json.loads(bytes(handler_res.body).decode("utf-8"))
    assert h_body["code"] == "NOT_FOUND"
    assert h_body["details"] == {"id": 999}


@pytest.mark.asyncio
async def test_unhandled_exception_handler_direct() -> None:
    """Verify unhandled_exception_handler converts raw exceptions to safe 500 error."""
    scope = {"type": "http", "method": "GET", "path": "/crash", "headers": []}
    req = Request(scope)
    res = await unhandled_exception_handler(req, RuntimeError("Database credentials in trace"))
    assert res.status_code == 500
    data = json.loads(bytes(res.body).decode("utf-8"))
    assert data["code"] == "INTERNAL_SERVER_ERROR"
    assert "Database" not in json.dumps(data)
    assert "credentials" not in json.dumps(data)


@pytest.mark.asyncio
async def test_http_exception_handler_direct() -> None:
    """Verify http_exception_handler handles Starlette HTTP exceptions."""
    scope = {"type": "http", "method": "GET", "path": "/forbidden", "headers": []}
    req = Request(scope)
    res = await http_exception_handler(
        req, StarletteHTTPException(status_code=403, detail="Forbidden access")
    )
    assert res.status_code == 403
    data = json.loads(bytes(res.body).decode("utf-8"))
    assert data["code"] == "FORBIDDEN"
    assert data["message"] == "Forbidden access"
