# Development Setup Guide

Multi-Agent Legacy Code Modernization Platform — Control Plane Service.

---

## 1. Supported Python Version & Prerequisites

- **Python**: `>=3.12` (Tested on Python 3.12, 3.13, and 3.14).
- **Package Manager**: [`uv`](https://docs.astral.sh/uv/) (v0.5+ recommended).
- **Container Engine**: Docker 24+ and Docker Compose v2+ (for containerized testing).
- **Git**: 2.40+.

---

## 2. Quickstart & Local Environment Setup

### 2.1 Clone Repository and Enter Directory
```bash
git clone <repository-url>
cd "Legacy code modernization platform"
```

### 2.2 Configure Backend Environment
Navigate to the `backend` directory (all backend Python tooling operates from `backend/`):
```bash
cd backend
cp .env.example .env
```
Review `.env` for local parameters. All default values in `.env.example` are secure and functional for local offline development.

### 2.3 Install Dependencies via uv
Install all locked production, development, and test dependencies from within `backend/`:
```bash
uv sync --frozen
```
If working with an active Python environment directly:
```bash
python -m uv sync --frozen
```
*(Tip: You can also run commands from the repository root using `uv --directory backend sync --frozen`.)*

---

## 3. Configuration Reference

Configuration is managed via Pydantic Settings in `backend/modernization_platform/config/settings.py` and loaded from environment variables:

| Variable | Type | Default | Description |
|---|---|---|---|
| `APP_NAME` | string | `ModernizationPlatform` | Human-readable application name. |
| `APP_VERSION` | string | `0.1.0` | Semantic version string. |
| `ENVIRONMENT` | string | `development` | Runtime environment: `development`, `test`, `staging`, `production`. |
| `DEBUG` | boolean | `false` | Debug mode. **Strictly forbidden (`false`) in production.** |
| `HOST` | string | `0.0.0.0` | IP interface to bind ASGI server. |
| `PORT` | integer | `8000` | TCP port (1-65535). |
| `API_V1_PREFIX` | string | `/api/v1` | Prefix for version 1 API endpoints. |
| `ALLOWED_HOSTS` | list[str] | `["*"]` | Allowed HTTP Host headers. Wildcard forbidden in staging/production. |
| `CORS_ALLOWED_ORIGINS` | list[str] | `["http://localhost:3000"]` | Allowed origins for CORS requests. |
| `CORS_ALLOW_CREDENTIALS` | boolean | `true` | Permit cookies/credentials cross-origin. |
| `DOCS_ENABLED` | boolean | `true` | Expose `/docs`, `/redoc`, and `/openapi.json`. Recommended `false` in production. |
| `LOG_LEVEL` | string | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `LOG_FORMAT` | string | `console` | `console` for local dev; `json` for production structured logs. |
| `CORRELATION_HEADER_NAME` | string | `X-Correlation-ID` | HTTP header name for request correlation. |
| `HEALTH_CHECK_TIMEOUT_SECONDS` | float | `5.0` | Timeout threshold for individual readiness checks. |

---

## 4. Running the Application Locally

Start the ASGI server with hot-reload enabled (run from within `backend/`):
```bash
cd backend
uv run uvicorn modernization_platform.main:app --host 127.0.0.1 --port 8000 --reload
```
Or directly using Python:
```bash
python -m uvicorn modernization_platform.main:app --host 127.0.0.1 --port 8000 --reload
```
*(Or from the repository root: `uv --directory backend run uvicorn modernization_platform.main:app --host 127.0.0.1 --port 8000 --reload`)*

---

## 5. Health & Diagnostic Endpoints

### 5.1 Liveness Endpoint
Reports if the Python ASGI process is running and accepting traffic:
```bash
curl -i http://127.0.0.1:8000/health/live
```
**Response:**
```json
{
  "status": "alive",
  "timestamp": "2026-10-15T10:15:00.000000+00:00",
  "version": "0.1.0"
}
```

### 5.2 Readiness Endpoint
Evaluates whether the service and downstream dependencies are healthy:
```bash
curl -i http://127.0.0.1:8000/health/ready
```
**Response (HTTP 200 OK):**
```json
{
  "status": "ready",
  "timestamp": "2026-10-15T10:15:00.000000+00:00",
  "probes": {}
}
```
*(In Phase 01.1, readiness evaluates registered core probes. Future phases register PostgreSQL and MinIO probes via `readiness_registry.register_probe()`.)*

---

## 6. Testing, Linting & Quality Toolchain

The project enforces strict automated quality gates. All commands below are run from within the `backend/` directory (or prefixed with `uv --directory backend run ...`).

```bash
cd backend
```

### 6.1 Run Automated Tests with Coverage
```bash
uv run pytest --cov=modernization_platform --cov-report=term-missing
```
*(Minimum baseline coverage threshold: **85%**).*

### 6.2 Code Formatting & Linting
```bash
# Format check
uv run ruff format --check .

# Auto-format
uv run ruff format .

# Linting
uv run ruff check .

# Auto-fix linting issues
uv run ruff check --fix .
```

### 6.3 Static Type Checking (mypy strict)
```bash
uv run mypy modernization_platform tests
```

### 6.4 Rule 1 AST Compliance Test
Verifies that all backend functions wrap their bodies in `try/except` (or `@log_errors`), log with traceback, and never silently swallow exceptions:
```bash
uv run pytest tests/unit/test_rule_1_enforcement.py -v
```

---

## 7. Lockfile Maintenance

Dependencies are locked reproducibly in `backend/uv.lock`. Always execute lock commands from `backend/`:

```bash
cd backend
```

### Add or Update Dependencies
To add a production dependency:
```bash
uv add <package-name>
```
To add a development or testing dependency:
```bash
uv add --dev <package-name>
```
To re-generate or check lockfile consistency:
```bash
uv lock
uv lock --check
```

---

## 8. Container Build and Run Instructions

### 8.1 Production Container Build
From the repository root:
```bash
docker build -t modernization-platform:latest -f backend/Dockerfile backend
```
Or from within `backend/`:
```bash
docker build -t modernization-platform:latest -f Dockerfile .
```
Run production container (runs as non-root user `10001:10001` on port 8000):
```bash
docker run --rm -p 8000:8000 modernization-platform:latest
```

### 8.2 Development Container with Docker Compose
From repository root:
```bash
docker compose up --build
```
Or referencing infrastructure compose directly:
```bash
docker compose -f infrastructure/compose.yaml up --build
```
This mounts `./backend/src` and `./backend/tests` into the container with hot-reload enabled.

---

## 9. Security Notes for Local Development

1. **Secrets**: Never commit `.env` or files containing credentials. Git pre-commit hooks and `.gitignore` guard against secret leaks.
2. **Log Redaction**: Structured logs automatically redact passwords, API keys, Bearer tokens, and private keys via `RedactingFilter`.
3. **Correlation IDs**: All requests automatically receive an `X-Correlation-ID`. Injected headers with malicious characters or oversized strings are discarded and replaced with valid UUIDs.
4. **Untrusted Code**: Phase 01.1 is strictly the control plane. Legacy code execution occurs exclusively within sandboxed containers in later phases.
