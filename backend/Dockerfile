# syntax=docker/dockerfile:1.7

# ==============================================================================
# Multi-stage Production Dockerfile for Modernization Platform Control Plane
# ==============================================================================

# Build Stage
FROM python:3.12-slim-bookworm AS builder

# Prevent python from writing pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Install uv for fast, deterministic dependency compilation
COPY --from=ghcr.io/astral-sh/uv:0.5.21 /uv /uvx /bin/

# Copy packaging specifications
COPY pyproject.toml uv.lock ./

# Install production dependencies into a standalone virtual environment
RUN uv sync --frozen --no-dev --no-install-project

# Copy source tree and install project package
COPY src ./src
RUN uv sync --frozen --no-dev

# ==============================================================================
# Production Runtime Stage
# ==============================================================================
FROM python:3.12-slim-bookworm AS runner

# Security hardening: establish non-root user and group
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /sbin/nologin -M appuser

WORKDIR /app

# Ensure standard runtime variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    ENVIRONMENT=production \
    HOST=0.0.0.0 \
    PORT=8000

# Copy compiled virtual environment and project code from builder stage
COPY --from=builder --chown=appuser:appgroup /build/.venv /app/.venv
COPY --from=builder --chown=appuser:appgroup /build/src /app/src

# Drop all privileges and run as non-root
USER 10001:10001

EXPOSE 8000

# Container health check utilizing process liveness endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)" || exit 1

# Production startup command
CMD ["uvicorn", "modernization_platform.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
