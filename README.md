# Multi-Agent Legacy Code Modernization Platform

[![CI Quality Gate](https://github.com/organization/legacy-code-modernization-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/organization/legacy-code-modernization-platform/actions/workflows/ci.yml)
[![Python 3.12 | 3.13 | 3.14](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://www.python.org/)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy.readthedocs.io/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Coverage](https://img.shields.io/badge/coverage-85.6%25-brightgreen.svg)](https://github.com/organization/legacy-code-modernization-platform)

An enterprise-grade, multi-agent control plane platform designed to modernize legacy codebases into modern target technology stacks with behavioral equivalence verification, human-in-the-loop approval gates (G1–G4), and strict cost controls.

---

## Repository Structure

The platform is organized as a clean, modular monorepo cleanly isolating backend services, infrastructure definitions, documentation, and continuous integration workflows:

```text
legacy-code-modernization-platform/
├── backend/                        # Python FastAPI backend application & toolchain
│   ├── src/
│   │   └── modernization_platform/ # Modular application package
│   │       ├── api/                # FastAPI routers and endpoints
│   │       ├── core/               # Errors, hashing, IDs, and shared utilities
│   │       ├── config/             # Pydantic Settings and environment validation
│   │       ├── domain/             # Domain logic and models
│   │       ├── schemas/            # Pydantic request/response/artifact schemas
│   │       ├── repositories/       # Data access and persistence layers
│   │       ├── services/           # Business domain services
│   │       ├── workflows/          # Orchestration and workflow definitions
│   │       ├── workers/            # Asynchronous background task workers
│   │       ├── integrations/       # External service adapters
│   │       ├── storage/            # Object storage interfaces
│   │       ├── security/           # Secret scanning, redaction, and authz
│   │       └── observability/      # Structured logging, metrics, correlation IDs
│   ├── tests/                      # Python automated test suite
│   │   ├── unit/                   # Fast isolated unit tests & Rule 1 AST scanner
│   │   ├── integration/            # Component & service integration tests
│   │   ├── contract/               # Schema and API contract tests
│   │   └── security/               # Security policy & redaction tests
│   ├── pyproject.toml              # Backend package configuration & tool definitions
│   ├── uv.lock                     # Pinned reproducible lockfile
│   ├── Dockerfile                  # Production multi-stage non-root container
│   ├── Dockerfile.dev              # Development hot-reload container
│   └── .env.example                # Backend-specific environment template
│
├── infrastructure/                 # Deployment and container orchestration
│   ├── docker/                     # Dedicated Docker configurations
│   ├── monitoring/                 # Dashboards, metrics, and alerting configs
│   └── compose.yaml                # Infrastructure Compose definitions
│
├── docs/                           # Architecture, specifications, and runbooks
│   ├── architecture/               # Architectural designs & repository structure
│   ├── development-setup.md        # Detailed developer onboarding guide
│   ├── production-engineering-rules.md # Production engineering & Rule 1 standards
│   ├── TDD.md                      # Technical Design Document
│   ├── PRD.md                      # Product Requirements Document
│   └── Implementation.md           # Implementation phase tracker & Definition of Done
│
├── .github/
│   └── workflows/
│       └── ci.yml                  # GitHub Actions CI pipeline
│
├── compose.yaml                    # Root developer convenience Compose entrypoint
├── .env.example                    # Root environment configuration template
└── README.md                       # Monorepo overview and quickstart
```

For complete details on architectural decisions, separation of concerns, and extension guidelines, see [Repository Structure Architecture](docs/architecture/repository-structure.md).

---

## Backend Setup & Environment Configuration

### Prerequisites
- Python `>= 3.12` (Python 3.12, 3.13, or 3.14)
- `uv` package manager (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Docker & Docker Compose (optional, for containerized workflows)

### 1. Environment Configuration
Navigate to the `backend/` directory and create your local environment file:
```bash
cd backend
cp .env.example .env
```
*(All defaults in `backend/.env.example` are secure and functional for local offline development).*

### 2. Dependency Installation
Install all locked production, development, and test dependencies:
```bash
uv sync --frozen
```
Or with direct Python interpreter:
```bash
python -m uv sync --frozen
```

---

## Running the Application Locally

Start the ASGI server with hot-reload enabled:
```bash
cd backend
uv run uvicorn modernization_platform.main:app --host 127.0.0.1 --port 8000 --reload
```
*(Tip: You can also start the server from the repository root via `uv --directory backend run uvicorn modernization_platform.main:app --host 127.0.0.1 --port 8000 --reload`)*

### Verify Endpoints
```bash
# Process liveness
curl -i http://127.0.0.1:8000/health/live

# Service readiness
curl -i http://127.0.0.1:8000/health/ready
```

---

## Testing, Linting & Quality Toolchain

The backend enforces strict automated quality gates. All quality commands are run within `backend/`:

```bash
cd backend

# 1. Format check
uv run ruff format --check .

# 2. Lint check
uv run ruff check .

# 3. Static type check (mypy strict mode)
uv run mypy src tests

# 4. Automated tests with coverage (minimum baseline: 85%)
uv run pytest --cov=src/modernization_platform --cov-report=term-missing

# 5. Rule 1 AST compliance check
uv run pytest tests/unit/test_rule_1_enforcement.py -v
```

---

## Container & Docker Compose Workflows

### Build Production Container
From the repository root:
```bash
docker build -t modernization-platform:latest -f backend/Dockerfile backend
```

### Run with Docker Compose
Start the service in development mode with live code reloading:
```bash
docker compose up --build
```
Or using the infrastructure Compose file:
```bash
docker compose -f infrastructure/compose.yaml up --build
```

---

## Documentation Links

- [Repository Structure Guide](docs/architecture/repository-structure.md): Monorepo organization, directory roles, and module addition guidelines.
- [Development Setup Guide](docs/development-setup.md): Comprehensive onboarding and local development reference.
- [Phase 01.1 Architecture Guide](docs/architecture/phase-01-1-foundation.md): Control plane design, correlation tracing, error modeling, and probe registry.
- [Production Engineering Rules](docs/production-engineering-rules.md): Non-negotiable quality, security, and error-handling standards.
- [Technical Design Document (TDD)](docs/TDD.md): Platform architecture, multi-agent workflows, and gate specifications.
- [Implementation Guide](docs/Implementation.md): Milestone tracker, phase deliverables, and acceptance criteria.

