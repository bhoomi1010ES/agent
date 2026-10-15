# Alembic Migration Governance & Local pgAdmin Runbook
## Multi-Agent Legacy Code Modernization Platform — Sub-Phase 01.2

This document governs schema evolution, migration generation, safety procedures, and local pgAdmin / PostgreSQL instructions.

---

## 1. Migration Philosophy & Rules

1. **Explicit Pre-Deployment Step**: Migrations must **never** be executed automatically during ordinary application startup (`create_app` or `uvicorn`). Application instances start concurrently; racing DDL migrations across replicas causes deadlocks and corrupted schema versions.
2. **Deterministic & Reversible**: Every migration must define an explicit `upgrade()` and `downgrade()`. Where a change is irreversible (e.g. data truncation), this must be explicitly documented.
3. **No Unreviewed Autogeneration**: `alembic revision --autogenerate` is a generation convenience, not a substitute for review. All generated operations, constraint names, and column types must be manually inspected.
4. **Zero-Downtime Awareness**: For production schema updates, avoid table locks (`ALTER TABLE ... ADD COLUMN ... DEFAULT` with heavy rewrites).

---

## 2. Local pgAdmin / PostgreSQL Setup

When developing locally using pgAdmin on Windows without Docker:

### Step 1: Create the Platform Databases in pgAdmin
1. Open **pgAdmin 4**.
2. Connect to your local PostgreSQL server (typically running on `localhost:5432` with user `postgres`).
3. Right-click **Databases** -> **Create** -> **Database...**
   - Database name: `modernization_dev` (for development and API execution).
4. Create a second database:
   - Database name: `modernization_test` (for running integration tests).

### Step 2: Configure Environment Variables
Create or update `backend/.env`:
```ini
# Development connection string
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/modernization_dev

# Dedicated test connection string
DATABASE_TEST_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/modernization_test
```

---

## 3. Standard Migration Commands

All commands are executed from the `backend/` directory using the project's Python environment:

### Check Current Migration Status
```bash
# Show currently applied revision
alembic current

# Show full migration history
alembic history --verbose
```

### Apply Migrations (Upgrade)
```bash
# Upgrade development database to latest schema
alembic upgrade head

# Explicitly target a specific database URL (e.g. pgAdmin test database)
alembic -x db_url=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/modernization_dev upgrade head
```

### Dry Run / Offline SQL Generation
Generate SQL DDL script without touching any database:
```bash
alembic upgrade head --sql
```

### Rollback (Downgrade)
```bash
# Roll back one revision
alembic downgrade -1

# Roll back all migrations to clean base
alembic downgrade base
```

### Creating New Revisions
```bash
alembic revision -m "descriptive_change_summary"
```

---

## 4. Initial Migration (`0001_initial_schema`)

The baseline schema migration is located at:
`backend/migrations/versions/0001_initial_persistence_schema.py`

This migration creates:
- Core tables: `job`, `artifact`, `module`, `module_attempt`, `agent_run`, `test_case`, `test_result`, `gate`, `gate_decision`, `audit_event`.
- All foreign keys with explicit deletion rules (`CASCADE`, `RESTRICT`, `SET NULL`).
- Composite unique constraints (e.g., `(job_id, type, version)`).
- Check constraints enforcing state enums and positive attempt counters.
- Performance indexes on frequently queried foreign keys and status fields.
