# Modernization Platform Backend

FastAPI control plane service for the Multi-Agent Legacy Code Modernization Platform.

## Quickstart

From within the `backend/` directory:

```bash
# 1. Install dependencies
uv sync --frozen

# 2. Run local development server
uv run uvicorn modernization_platform.main:app --host 127.0.0.1 --port 8000 --reload

# 3. Run tests with coverage
uv run pytest --cov=modernization_platform --cov-report=term-missing
```

See [`../docs/development-setup.md`](../docs/development-setup.md) for full setup instructions.
