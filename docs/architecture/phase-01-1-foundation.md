# Phase 01.1 Foundation Architecture

## 1. Architectural Overview

Phase 01.1 establishes the foundational engineering runtime, package structure, and control-plane backbone for the Multi-Agent Legacy Code Modernization Platform. It adheres strictly to the approved Technical Design Document (`docs/TDD.md`) and Production Engineering Rules (`docs/production-engineering-rules.md`).

---

## 2. Package Responsibilities

The codebase follows the standard `src/` layout under the top-level package `modernization_platform`:

```text
src/modernization_platform/
├── main.py              # Minimal ASGI entry point callable by Uvicorn / Gunicorn
├── app.py               # FastAPI application factory (create_app) and lifespan lifecycle manager
├── config/              # Centralized Pydantic Settings configuration and validation
│   └── settings.py
├── core/                # Core runtime primitives, errors, IDs, logging, and middleware
│   ├── decorators.py    # Rule 1 error logging decorator (@log_errors)
│   ├── exceptions.py    # ModernizerError hierarchy and HTTP ApplicationExceptions
│   ├── ids.py           # Correlation ID generation, sanitization, and contextvars management
│   ├── logging.py       # JSONFormatter, ConsoleFormatter, and RedactingFilter
│   └── middleware.py    # CorrelationIdMiddleware and RFC 9457 exception handlers
├── api/                 # Transport layer (thin route adapters)
│   └── v1/
│       ├── router.py    # Aggregator for all v1 route modules
│       └── endpoints/
│           └── health.py # Liveness and readiness endpoints with extensible probe registry
│
# Extension Boundary Packages (Future Phases)
├── db/                  # SQLAlchemy models, sessions, and engine setup (Phase 01.2)
├── domain/              # Core domain entities and state machines (Phase 01.2+)
├── schemas/             # Pydantic artifact contracts (RepoInventory, LegacyModel, etc.) (Phase 02)
├── repositories/        # Database data access layer (Phase 01.2)
├── services/            # Application and orchestration services (Phase 06)
├── workflows/           # LangGraph graph definitions and checkpointing (Phase 06)
├── workers/             # Task leasing and background worker loops (Phase 06)
├── integrations/        # Git host adapters (Gitea, GitHub) and model adapters (Phase 03, 12)
├── storage/             # Content-addressed object store client (S3/MinIO) (Phase 01.2)
├── security/            # Secret scanning, PII redaction, and RBAC authorization (Phase 04)
└── observability/       # OpenTelemetry spans, traces, and metrics (Phase 14)
```

---

## 3. Application Lifecycle & Startup Sequence

1. **Instantiation**: `create_app(settings=None)` is called by the ASGI runner (`main.py`) or test harness.
2. **Configuration Loading**: Pydantic Settings validates all environment variables against strict schema types and production invariants.
3. **Logging Initialization**: `setup_logging()` installs the `RedactingFilter` and configures `JSONFormatter` (production) or `ConsoleFormatter` (development) on the root logger, muting redundant third-party logs.
4. **Middleware Registration**:
   - `CorrelationIdMiddleware` is registered to ensure every incoming HTTP request receives a validated correlation ID.
   - `CORSMiddleware` applies environment-specific origins.
   - `TrustedHostMiddleware` is conditionally applied when `allowed_hosts` is restricted.
5. **Exception Handlers**: Centralized handlers intercept `ApplicationException`, `RequestValidationError`, `StarletteHTTPException`, and generic `Exception`.
6. **Route Registration**: Mounts `/health` liveness/readiness routes and versioned `/api/v1` routes.
7. **Lifespan Startup**: When the ASGI server launches, `lifespan(app)` executes startup events, logging application version, environment, and debug state. On process termination, `lifespan(app)` initiates graceful shutdown.

---

## 4. Request Correlation & Context Propagation

- **Header Resolution**: The middleware inspects the incoming request header (default `X-Correlation-ID` with fallback to `X-Request-ID`).
- **Validation**: Headers must match `^[a-zA-Z0-9_\-]{1,64}$`. Unsafe headers (containing CRLF characters, HTML/JS injection payloads, or length > 64 chars) are rejected.
- **Context Injection**: Valid or freshly generated UUIDv4 IDs are stored in an asynchronous `contextvars.ContextVar`.
- **Egress & Response**: The correlation ID is echoed in the response headers and embedded in all structured log records and API error responses (`request_id`).

---

## 5. Standardized Error Handling (RFC 9457)

All API errors return consistent JSON responses:

```json
{
  "code": "RESOURCE_NOT_FOUND",
  "message": "The requested item was not found.",
  "request_id": "a9d3e86c-4821-4d10-8bbf-931d8e178c12",
  "details": {
    "item_id": 123
  }
}
```

- **Validation Errors (422)**: FastAPI / Pydantic schema validation errors are transformed into safe field-level issues without leaking internal code representations.
- **Unhandled Errors (500)**: Generic exceptions are caught, logged internally with full traceback and correlation ID, and returned to clients as a safe generic message without exposing file paths, connection strings, credentials, or stack traces.

---

## 6. Health & Readiness Probe Architecture

- **`GET /health/live`**: Fast process liveness check for Kubernetes/container runtimes. Returns HTTP 200 immediately if the event loop is active.
- **`GET /health/ready`**: Verifies whether platform services are ready to process workloads.
- **Readiness Registry**: An extensible `ReadinessProbeRegistry` allows future phases to register asynchronous health checks:
  ```python
  from modernization_platform.api.v1.endpoints.health import readiness_registry

  readiness_registry.register_probe("postgres", check_database_connection)
  ```
- If any mandatory probe fails or times out, `/health/ready` returns HTTP 503 Service Unavailable with structured probe diagnostics.

---

## 7. Deferred Features (Phase 01.2 and Later)

To preserve architectural integrity and avoid premature abstraction, the following components are deliberately deferred to their designated phases:
- **Phase 01.2**: PostgreSQL database schema, Alembic migrations, SQLAlchemy repositories, MinIO S3 object storage client.
- **Phase 02**: Pydantic artifact models (`RepoInventory`, `LegacyModel`, `TargetBlueprint`, etc.).
- **Phase 03**: Model Gateway adapter (Ollama local, OpenRouter cloud).
- **Phase 04**: Secret scanning and PII redaction pipeline, JWT/OIDC authentication.
- **Phase 05**: Isolated Docker sandboxes for untrusted code execution.
- **Phase 06**: LangGraph supervisor, PostgreSQL-based task leasing, and approval gates.
