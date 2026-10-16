# Phase 1 Operational Runbook: Legacy Modernization Platform

## 1. Document Overview
This document serves as the authoritative operational runbook for Phase 1 of the Legacy Modernization Platform. It provides standard operating procedures (SOPs) for deployment, service management, disaster recovery, incident mitigation, and operational monitoring.

---

## 2. Platform Architecture & Service Inventory

| Component | Technology | Role | Port / Endpoint |
|---|---|---|---|
| **Control Plane API** | FastAPI / Uvicorn | REST API, Auth, Job Management, Gate Operations, Gateway | `:8000` |
| **Worker Runtime** | Python 3.12+ AsyncIO | Background Task Execution, Model Invocation, Agent Loops | Background daemon |
| **Relational Database** | PostgreSQL 16+ / 18 | Durable State, Checkpoints, Audits, Budgets, Leases | `:5432` |
| **Object Storage** | S3 / MinIO / Local FS | Artifact Storage, ASTs, Source Code Archives | S3 API / Mount |
| **Observability** | OpenTelemetry / JSON Logs | Distributed Tracing, Structured Logging, Metrics | Stdout / OTel Collector |

---

## 3. Environment Startup & Initialization

### 3.1 Prerequisites
- Python 3.12 or higher (verified with Python 3.13)
- PostgreSQL 16+ running on `localhost:5432` or reachable host
- Node/Git/Docker (optional, for local containerized runtime)

### 3.2 Database Migration Execution
Before launching application services, execute all Alembic migrations to bring the schema to head:
```powershell
cd c:\Users\lenovo\Desktop\agent\backend
.venv\Scripts\alembic upgrade head
```
Expected output:
```text
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade -> 001_initial_schema
...
INFO  [alembic.runtime.migration] Running upgrade -> 010_model_gateway_and_budgets
```

### 3.3 Backend API Startup
Launch the FastAPI control plane:
```powershell
.venv\Scripts\uvicorn modernization_platform.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 3.4 Worker Process Startup
Launch worker daemons with unique worker identifiers:
```powershell
$env:WORKER_ID="worker-prod-$(New-Guid)"
.venv\Scripts\python -m modernization_platform.workers.runtime
```

---

## 4. Health & Readiness Verification

The platform exposes three standard Kubernetes-compliant health endpoints:

### 4.1 Liveness Probe (`GET /health/live`)
- **Purpose**: Checks if the web server process is alive and responding.
- **Expected Status**: `HTTP 200 OK`
- **Response**: `{"status": "alive"}`

### 4.2 Readiness Probe (`GET /health/ready`)
- **Purpose**: Verifies that PostgreSQL database connectivity, connection pooling, and downstream storage are operational.
- **Expected Status**: `HTTP 200 OK`
- **Response**: `{"status": "ready", "database": "connected", "storage": "available"}`

### 4.3 Startup Probe (`GET /health/startup`)
- **Purpose**: Confirms initial database migrations and schema consistency are satisfied.
- **Expected Status**: `HTTP 200 OK`

---

## 5. Routine Operations & Maintenance

### 5.1 Database Backup SOP (`pg_dump`)
Execute daily automated and pre-deployment backups using transactional inserts or custom binary formats:
```powershell
# Transactional SQL Insert Backup
$env:PGPASSWORD="<db_password>"
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" -h localhost -p 5432 -U postgres -d modernization_platform --inserts --data-only -f "backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql"
```

### 5.2 Database Restoration SOP (`psql`)
To restore from a backup:
```powershell
# 1. Stop backend services and worker daemons
# 2. Restore into target database
$env:PGPASSWORD="<db_password>"
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" -h localhost -p 5432 -U postgres -d modernization_platform -f "backup_target.sql"

# 3. Verify row counts and integrity
# 4. Restart backend services
```

### 5.3 Schema Migration Rollback SOP
If an erroneous migration requires rollback:
```powershell
# Downgrade 1 revision
.venv\Scripts\alembic downgrade -1

# Downgrade to a specific revision
.venv\Scripts\alembic downgrade <revision_id>
```

---

## 6. Incident Response & Failure Recovery

### 6.1 Worker Process Crash & Lease Recovery
- **Symptom**: Task remains in `leased` status but worker PID has vanished or heartbeats have stopped.
- **Automated Behavior**:
  - The platform lease manager maintains an `expires_at` timestamp on each task lease (default: 300s).
  - When a lease expires, another active worker automatically reclaims the task via atomic SQL `FOR UPDATE SKIP LOCKED`.
  - Stale worker completion attempts are rejected with `LeaseLostError` via fencing tokens.
- **Manual Intervention**:
  - Check worker logs for Out-Of-Memory (OOM) or unhandled exceptions.
  - Restart the dead worker process:
    ```powershell
    .venv\Scripts\python -m modernization_platform.workers.runtime
    ```

### 6.2 Human Gate Timeout & Recovery
- **Symptom**: Gate remains in `PENDING` state beyond the configured SLA (default: 24h).
- **Automated Behavior**:
  - When the gate timeout expires without human decision, the gate automatically transitions to `PAUSED`.
  - The workflow is safely suspended; it does NOT proceed or approve without authorization.
- **Manual Intervention**:
  1. Call `POST /api/v1/gates/{gate_id}/resume` to unpause the gate.
  2. The authorized Approver/Admin submits a valid approval or rejection with mandatory rationale.

### 6.3 Gate Rejection Handling
- **Symptom**: Reviewer or Approver rejects the artifact at G1, G2, G3, or G4.
- **Platform Behavior**:
  - Rejection requires non-empty feedback string (enforced at API and domain levels).
  - Gate transitions to `REJECTED`.
  - Workflow rolls back to the corresponding engineering stage (`analysis`, `architecture`, or `conversion`).
  - Worker initiates rework, producing a incremented artifact version (e.g., v2).
  - Stale approvals of prior artifact versions are rejected with `StaleArtifactVersionError`.

### 6.4 Model Provider Outage & Fallback Routing
- **Symptom**: Primary provider returns HTTP 500, 502, 503, connection timeouts, or HTTP 429 rate limits.
- **Automated Behavior**:
  - Rate limits (429) and transient network failures trigger exponential backoff retries up to configured retry limits (default: 3).
  - If the primary provider remains unreachable, the Model Gateway routes the request to approved fallback providers defined in the agent's `ModelPolicy`.
  - The fallback execution runs inside the identical pre-reserved budget allocation.
- **Manual Intervention**:
  - If all providers in the fallback chain fail, the Gateway raises `ExhaustedFallbackError`.
  - The task transitions to `retryable` or pauses the job workflow until upstream provider availability recovers.

### 6.5 Model Budget Exhaustion (80% & 100% Limits)
- **Symptom**: Model calls are blocked with `ModelBudgetExceededError`.
- **Automated Behavior**:
  - When spend + reservations reaches 80% of `limit_microcents`, a `BUDGET_WARNING_80_PERCENT` audit event is emitted exactly once.
  - When spend + reservations reaches 100%, execution is hard-stopped BEFORE calling external provider APIs.
- **Manual Intervention / Budget Increase**:
  - An Admin or Job Owner updates the job budget account:
    ```http
    PATCH /api/v1/jobs/{job_id}/budget
    Content-Type: application/json

    {
      "additional_budget_microcents": 50000000
    }
    ```
  - Resume the paused workflow via `POST /api/v1/jobs/{job_id}/resume`.

### 6.6 Database Connection Pool Exhaustion
- **Symptom**: API endpoints return HTTP 500 with `asyncpg.exceptions.TooManyConnectionsError` or pool timeout.
- **Recovery Procedure**:
  1. Check PostgreSQL active connections:
     ```sql
     SELECT count(*), state FROM pg_stat_activity GROUP BY state;
     ```
  2. Increase `pool_size` and `max_overflow` in `Settings` (`DB_POOL_SIZE=30`, `DB_MAX_OVERFLOW=20`).
  3. Ensure all background queries use transactional scopes and context managers (`async with session_factory() as session:`).

---

## 7. Security & Observability Operations

### 7.1 Secret Leakage & Credential Rotation SOP
1. If an API key or database password is compromised:
   - Immediately rotate the credential in the external secret manager (AWS Secrets Manager, GCP Secret Manager, Vault).
   - Update `.env` or container environment variables.
   - Restart all backend and worker processes.
2. Verify audit logs:
   - Search `audit_event` and `model_execution` tables for unauthorized activity.
   - Run `detect-secrets scan` across repository and logs.

### 7.2 Distributed Trace Investigation
- Every HTTP request, task execution, and model invocation carries a structured `X-Correlation-ID`.
- To trace an end-to-end user request:
  ```powershell
  # Filter structured logs by correlation ID
  Get-Content app.log | Select-String "corr-job-12345"
  ```
- In OpenTelemetry UI / Jaeger, search by trace tag `correlation_id: <id>`.

---

## 8. Pre-Release Operational Checklist

Before approving release to production, operators must verify:
- [x] Database migrations up to date (`alembic upgrade head` verified)
- [x] All 542 automated regression tests pass
- [x] Zero High or Critical Bandit findings
- [x] Zero vulnerable dependencies reported by `pip-audit`
- [x] Zero leaked secrets verified by `detect-secrets`
- [x] Production Docker container runs as non-root UID 10001
- [x] Health check endpoints return HTTP 200 (`/health/live`, `/health/ready`)
- [x] Database backup and restore verified via test suite
- [x] Audit trails verified append-only and immutable
