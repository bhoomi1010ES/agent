"""HTTP request-size protection tests."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.types import Message, Receive, Scope, Send

from modernization_platform.app import create_app
from modernization_platform.config.settings import Settings
from modernization_platform.core.middleware import RequestBodyLimitMiddleware


@pytest.mark.asyncio
async def test_oversized_request_is_rejected_before_authentication() -> None:
    settings = Settings(environment="test", debug=False, max_request_body_bytes=1_024)
    app = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/jobs/00000000-0000-0000-0000-000000000000/gates/"
            "00000000-0000-0000-0000-000000000000/decisions",
            content=b"x" * 1_025,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json()["code"] == "REQUEST_TOO_LARGE"


@pytest.mark.asyncio
async def test_chunked_body_limit_stops_reading_when_limit_is_crossed() -> None:
    messages: list[Message] = [
        {"type": "http.request", "body": b"x" * 900, "more_body": True},
        {"type": "http.request", "body": b"x" * 200, "more_body": True},
        {"type": "http.request", "body": b"x" * 2_000, "more_body": True},
    ]
    received = 0
    sent: list[Message] = []
    app_called = False

    async def receive() -> Message:
        nonlocal received
        message = messages[received]
        received += 1
        return message

    async def send(message: Message) -> None:
        sent.append(message)

    async def inner_app(_scope: Scope, _receive: Receive, _send: Send) -> None:
        nonlocal app_called
        app_called = True

    middleware = RequestBodyLimitMiddleware(inner_app, max_body_bytes=1_024)
    scope: Scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/bounded",
        "raw_path": b"/bounded",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }
    await middleware(scope, receive, send)

    assert received == 2
    assert not app_called
    assert sent[0]["status"] == 413
