"""HTTP middleware and centralized exception handlers for standardized errors and correlation."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from modernization_platform.core.exceptions import ApplicationException
from modernization_platform.core.ids import (
    generate_correlation_id,
    get_correlation_id,
    is_valid_correlation_id,
    set_correlation_id,
)

logger = logging.getLogger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware extracting, validating, and propagating request correlation IDs."""

    def __init__(self, app: Any, header_name: str = "X-Correlation-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            # Check configured header, fallback to X-Request-ID
            incoming_id = request.headers.get(self.header_name) or request.headers.get(
                "X-Request-ID"
            )

            if incoming_id and is_valid_correlation_id(incoming_id):
                correlation_id = incoming_id
            else:
                correlation_id = generate_correlation_id()

            set_correlation_id(correlation_id)

            try:
                response = await call_next(request)
            except Exception as unhandled_exc:
                cid = get_correlation_id()
                logger.exception(
                    "Unhandled exception in request processing | path=%s correlation_id=%s | %s: %s",
                    request.url.path,
                    cid,
                    type(unhandled_exc).__name__,
                    unhandled_exc,
                )
                response = create_error_response(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    code="INTERNAL_SERVER_ERROR",
                    message="An unexpected server error occurred. Please contact support with the request ID.",
                )

            response.headers[self.header_name] = correlation_id
            return response
        except Exception as exc:
            cid = get_correlation_id()
            logger.exception(
                "Unhandled error in CorrelationIdMiddleware | correlation_id=%s | %s: %s",
                cid,
                type(exc).__name__,
                exc,
            )
            return create_error_response(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected server error occurred. Please contact support with the request ID.",
            )


def create_error_response(
    status_code: int,
    code: str,
    message: str,
    details: Any | None = None,
) -> JSONResponse:
    """Create a standardized API error response conforming to the platform contract."""
    try:
        correlation_id = get_correlation_id()
        content = {
            "code": code,
            "message": message,
            "request_id": correlation_id,
            "details": details,
        }
        return JSONResponse(
            status_code=status_code,
            content=content,
            headers={"X-Correlation-ID": correlation_id},
        )
    except Exception as exc:
        logger.exception("create_error_response failed | %s: %s", type(exc).__name__, exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An error occurred",
                "request_id": "",
                "details": None,
            },
        )


async def application_exception_handler(
    request: Request, exc: ApplicationException
) -> JSONResponse:
    """Handle custom application exceptions."""
    try:
        logger.warning(
            "Application exception on %s %s | code=%s message=%s",
            request.method,
            request.url.path,
            exc.code,
            exc.message,
        )
        return create_error_response(
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )
    except Exception as handler_exc:
        logger.exception(
            "application_exception_handler failed | %s: %s", type(handler_exc).__name__, handler_exc
        )
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="Internal error processing request",
        )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle request validation errors from FastAPI and Pydantic."""
    try:
        logger.warning(
            "Validation error on %s %s: %s",
            request.method,
            request.url.path,
            exc.errors(),
        )
        # Format validation errors safely without exposing raw code/internals
        safe_details = []
        for err in exc.errors():
            loc = " -> ".join(str(item) for item in err.get("loc", []))
            safe_details.append(
                {
                    "field": loc,
                    "issue": err.get("msg", "Invalid value"),
                    "type": err.get("type", "validation_error"),
                }
            )

        # HTTP 422 Unprocessable Content (RFC 9110)
        status_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
        return create_error_response(
            status_code=status_422,
            code="VALIDATION_ERROR",
            message="Request input validation failed.",
            details=safe_details,
        )
    except Exception as handler_exc:
        logger.exception(
            "validation_exception_handler failed | %s: %s", type(handler_exc).__name__, handler_exc
        )
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="Internal error during validation processing",
        )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle standard Starlette and FastAPI HTTP exceptions."""
    try:
        logger.info(
            "HTTP exception on %s %s: status=%d detail=%s",
            request.method,
            request.url.path,
            exc.status_code,
            exc.detail,
        )
        code_map = {
            status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
            status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
            status.HTTP_403_FORBIDDEN: "FORBIDDEN",
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
            status.HTTP_409_CONFLICT: "CONFLICT",
            status.HTTP_503_SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE",
        }
        code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
        return create_error_response(
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
        )
    except Exception as handler_exc:
        logger.exception(
            "http_exception_handler failed | %s: %s", type(handler_exc).__name__, handler_exc
        )
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="Internal error processing HTTP exception",
        )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fallback handler for any unhandled server errors.

    Logs full traceback internally with correlation ID, but returns a generic
    client-safe error message without leaking sensitive details or stack traces.
    """
    try:
        cid = get_correlation_id()
        logger.exception(
            "Unhandled server error on %s %s | correlation_id=%s | %s: %s",
            request.method,
            request.url.path,
            cid,
            type(exc).__name__,
            exc,
        )
        return create_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected server error occurred. Please contact support with the request ID.",
        )
    except Exception as fatal_exc:
        # Ultimate fallback
        logger.critical("Fatal exception in unhandled_exception_handler: %s", fatal_exc)
        return JSONResponse(
            status_code=500,
            content={
                "code": "INTERNAL_SERVER_ERROR",
                "message": "A fatal error occurred.",
                "request_id": get_correlation_id(),
                "details": None,
            },
        )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all centralized exception handlers on the FastAPI application instance."""
    try:
        app.add_exception_handler(ApplicationException, application_exception_handler)  # type: ignore[arg-type]
        app.add_exception_handler(RequestValidationError, validation_exception_handler)  # type: ignore[arg-type]
        app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
        app.add_exception_handler(Exception, unhandled_exception_handler)
    except Exception as exc:
        logger.exception("register_exception_handlers failed | %s: %s", type(exc).__name__, exc)
        raise
