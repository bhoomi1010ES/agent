# Phase 1 Release Evidence: Database Migration Validation

## 1. Migration Execution Summary

All database schema migrations were tested using Alembic against PostgreSQL in `tests/integration/db/test_migrations.py`:

- **Total Migrations**: 10 revisions
- **Test Result**: **PASS** (Executed in 3.29 seconds)
- **Lifecycle Tested**:
  1. Full upgrade from clean database to `head` (`010_model_gateway_and_budgets`).
  2. Full table, column, index, and foreign key constraint verification.
  3. Reversion / downgrade lifecycle down through intermediate checkpoints.
  4. Re-upgrade back to `head`.

---

## 2. Alembic Migration Revision Chain

| Rev ID | Revision Name | Description | Key Tables Introduced |
|---|---|---|---|
| `001` | `001_initial_schema` | Core tenant, identity, job foundation | `tenant`, `user_account`, `tenant_membership`, `job` |
| `002` | `002_add_job_budget_and_identity_columns` | Extended job budget and membership | `job_member`, budget columns on `job` |
| `003` | `003_add_storage_and_artifacts` | Artifact metadata and storage tracking | `artifact`, `artifact_lineage` |
| `004` | `004_add_audit_events` | Immutable platform audit logging | `audit_event` |
| `005` | `005_add_tasks_and_worker_leases` | Durable task queue and worker leases | `task`, `task_lease` |
| `006` | `006_add_agent_runs` | Agent execution runs and telemetry | `agent_run` |
| `007` | `007_add_workflow_checkpoints` | LangGraph durable checkpoints | `checkpoints`, `checkpoint_writes` |
| `008` | `008_add_human_gates` | G1–G4 human approval gates | `gate` |
| `009` | `009_add_gate_decisions` | Append-only human gate decisions | `gate_decision` |
| `010` | `010_model_gateway_and_budgets` | Model executions, accounts, and reservations | `model_execution`, `budget_account`, `budget_reservation` |

---

## 3. Schema Invariants & Foreign Key Constraints Verified

- `ON DELETE RESTRICT` on critical audit relations (`gate_decision -> gate`).
- `ON DELETE CASCADE` on job-scoped operational data (`task`, `artifact`, `budget_account`, `model_execution`).
- `ON DELETE SET NULL` on actor references (`gate_decision.actor_user_id`, `model_execution.task_id`).
- Check constraints enforcing non-negative integer microcents on `budget_account` and `budget_reservation`.
- Unique indices on `(tenant_id, slug)` and `(job_id, type, version)` for artifacts.
