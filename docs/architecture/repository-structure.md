# Repository Structure & Monorepo Architecture

This document describes the organizational layout, architectural boundaries, and guidelines for the **Multi-Agent Legacy Code Modernization Platform** codebase.

---

## 1. Architectural Philosophy

The repository follows a clean, modular monorepo structure designed to:
1. **Enforce Boundary Isolation**: Completely separate the backend control plane, frontend interfaces, infrastructure specifications, automated tests, and documentation.
2. **Support Autonomous Workflows**: Enable backend services and tests to be developed, containerized, and tested independently within `backend/`.
3. **Prevent Circular & Cross-Layer Coupling**: Ensure infrastructure definitions and documentation do not bleed into application runtime logic.
4. **Preserve Extension Boundaries**: Clearly designate future extension points (databases, agents, sandboxes, artifact schemas) without premature code scaffolding.

---

## 2. Directory Taxonomy

```text
legacy-code-modernization-platform/
│
├── backend/                           # Complete Python backend application
│   ├── src/
│   │   └── modernization_platform/    # Application package root
│   │       ├── __init__.py
│   │       ├── main.py                # ASGI entrypoint
│   │       ├── app.py                 # FastAPI application factory & lifespan
│   │       │
│   │       ├── api/                   # Transport layer (thin route adapters)
│   │       │   └── v1/
│   │       │       ├── router.py      # v1 router registry
│   │       │       └── endpoints/
│   │       │           └── health.py  # Liveness & readiness probes
│   │       │
│   │       ├── core/                  # Shared primitives & engineering standards
│   │       │   ├── exceptions.py      # Error hierarchy & RFC 9457 errors
│   │       │   ├── logging.py         # JSON logger & secret redactor
│   │       │   ├── middleware.py      # Correlation ID & exception middleware
│   │       │   ├── ids.py             # Correlation IDs & contextvars
│   │       │   └── decorators.py      # Rule 1 @log_errors decorator
│   │       │
│   │       ├── config/                # Centralized settings & validation
│   │       │   └── settings.py
│   │       │
│   │       # Extension Boundaries (Designated for Future Phases)
│   │       ├── db/                    # SQLAlchemy engine & session (Phase 01.2)
│   │       ├── domain/                # Core business entities & state (Phase 01.2+)
│   │       ├── schemas/               # Pydantic artifacts (RepoInventory, etc.) (Phase 02)
│   │       ├── repositories/          # Persistence repositories (Phase 01.2)
│   │       ├── services/              # Orchestration & domain services (Phase 06)
│   │       ├── workflows/             # LangGraph graphs & checkpointers (Phase 06)
│   │       ├── workers/               # Task leasing loops (Phase 06)
│   │       ├── integrations/          # Git & model provider adapters (Phase 03, 12)
│   │       ├── storage/               # MinIO S3 object storage (Phase 01.2)
│   │       ├── security/              # Secret scanning & RBAC (Phase 04)
│   │       └── observability/         # OpenTelemetry & metrics (Phase 14)
│   │
│   ├── tests/                         # Backend automated test suite
│   │   ├── unit/                      # Fast in-memory unit tests
│   │   ├── integration/               # API & probe integration tests
│   │   ├── conftest.py                # Global fixtures & test client
│   │   └── ...
│   │
│   ├── pyproject.toml                 # Package metadata, tool configurations, dependencies
│   ├── uv.lock                        # Pinned dependency lockfile
│   ├── Dockerfile                     # Multi-stage production container
│   ├── Dockerfile.dev                 # Development container with hot reload
│   ├── .dockerignore                  # Backend build exclusion rules
│   ├── .env.example                   # Backend-specific environment template
│   └── README.md                      # Backend service quickstart
│
├── infrastructure/                    # Deployment, compose, and container assets
│   ├── docker/                        # Curated base images & infrastructure assets
│   └── compose.yaml                   # Infrastructure-specific compose definition
│
├── docs/                              # Project-wide specifications & guides
│   ├── TDD.md                         # Technical Design Document
│   ├── PRD.md                         # Product Requirements Document
│   ├── TRD.md                         # Technical Requirements Document
│   ├── Implementation.md              # Phase-by-phase implementation guide
│   ├── production-engineering-rules.md# Mandatory engineering standards
│   ├── development-setup.md           # Developer onboarding & commands
│   ├── architecture/                  # Architectural deep-dives
│   │   ├── phase-01-1-foundation.md   # Phase 01.1 architecture reference
│   │   └── repository-structure.md    # This layout and boundaries document
│   └── timeline.md
│
├── .github/
│   └── workflows/
│       └── ci.yml                     # Central GitHub Actions CI pipeline
│
├── .gitignore                         # Project-wide Git ignore rules
├── .dockerignore                      # Root Docker build ignore rules
├── .env.example                       # Root shared environment template
├── compose.yaml                       # Root developer Compose entrypoint
├── backend_implementation_plan.md     # Detailed backend phase plan
├── ui_implementation_plan.md          # Detailed UI phase plan
└── README.md                          # Project overview & navigation index
```

---

## 3. Package Responsibilities in `backend/src/modernization_platform/`

- **`config/`**: Contains only declarative settings schemas (`settings.py`) using Pydantic Settings. Reads from environment variables, enforces fail-fast validation in staging/production, and rejects invalid configurations.
- **`core/`**: Houses shared infrastructure primitives:
  - Error and exception hierarchies (`exceptions.py`).
  - Correlation ID lifecycle and `contextvars` management (`ids.py`).
  - Structured logging, JSON formatters, and sensitive data redaction filters (`logging.py`).
  - Request middleware and centralized error formatting (`middleware.py`).
  - Production Engineering Rule 1 decorator (`decorators.py`).
- **`api/`**: Transport-level adapter. API routes are thin controllers that parse requests, invoke domain services, and return typed schemas. No business logic or database queries live in route handlers.
- **Extension Boundaries**: Packages such as `db/`, `domain/`, `schemas/`, `repositories/`, `services/`, `workflows/`, `workers/`, `integrations/`, `storage/`, `security/`, and `observability/` are designated boundaries for subsequent phases. Each contains a documented `__init__.py` establishing its purpose.

---

## 4. How to Add a New Backend Module

When introducing new functionality in future phases:

1. **Classify Responsibility**:
   - HTTP endpoint? Add to `backend/src/modernization_platform/api/v1/endpoints/` and register in `api/v1/router.py`.
   - Domain logic or coordinator? Add to `backend/src/modernization_platform/services/`.
   - Database model or repository? Add model to `backend/src/modernization_platform/domain/` or `db/` and repository to `repositories/`.
   - Pydantic contract artifact? Add to `backend/src/modernization_platform/schemas/`.
2. **Follow Rule 1 (production-engineering-rules.md)**:
   - Every function must wrap its body in `try/except` (or use the `@log_errors` decorator).
   - Log function name, correlation ID, exception type, and full traceback via `logger.exception`.
   - Never use bare `except:` or swallow exceptions with `pass`.
3. **Add Tests**:
   - Add unit tests under `backend/tests/unit/`.
   - Add integration tests under `backend/tests/integration/`.
   - Maintain minimum **85%** line coverage.
4. **Run Verification**:
   - `uv run ruff check .`
   - `uv run ruff format --check .`
   - `uv run mypy src tests`
   - `uv run pytest --cov=src/modernization_platform --cov-report=term-missing`
