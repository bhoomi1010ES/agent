# Phase 1 Release Evidence: Reliability & Failure Recovery Results

## 1. System Restart & Recovery Matrix

| Interruption Point | Persisted State | Recovery Mechanism | Duplicate Side Effects Allowed? | Test Verification |
|---|---|---|---|---|
| **Worker process crash during task** | `leased` with `expires_at` | Automatic lease expiration & reclaim by healthy worker | No (fencing token rejects stale worker) | `test_worker_crash_and_lease_recovery.py` |
| **Backend crash during workflow** | PostgreSQL durable checkpoint | LangGraph thread resume from latest state | No (idempotent step execution) | `test_postgres_durable_checkpoint_lifecycle.py` |
| **Model provider timeout / 5xx** | Pre-call budget reservation | Retry loop with backoff, then approved fallback target | No (reconciled spend) | `test_fallback_routing_on_primary_failure.py` |
| **Human Gate timeout** | `PENDING` gate record | Transitions to `PAUSED`; explicit resume required | No (workflow halted safely) | `test_gate_timeouts.py` |
| **Gate rejection** | Append-only `GateDecision` | Workflow rolls back to previous engineering stage | No (mandatory rationale enforced) | `test_gate_rejection_and_rework.py` |
| **Budget exhausted (100%)** | Account balance tracked | Outbound execution halted; job paused | No (hard limit prevents API call) | `test_budget_and_recovery_e2e.py` |
| **Database crash / restore** | Physical SQL / custom dump | Clean restore into fresh schema; live operations resume | No (full relational integrity) | `test_backup_restore.py` |

---

## 2. Worker Crash & Lease Recovery Evidence

Executed in `tests/integration/e2e/test_worker_crash_and_lease_recovery.py` and `tests/integration/tasks/test_crash_recovery.py`:
- **Scenario**: Worker 1 claims a background task and terminates without updating task state.
- **Verification**:
  - Lease timestamp expires.
  - Worker 2 queries for expired leases, successfully acquires task, increments `attempt_count` from 1 to 2.
  - Stale Worker 1 wakes up and attempts completion -> rejected with `LeaseLostError`.
  - Worker 2 completes task and produces expected artifact.
- **Result**: **PASS** (Zero duplicate processing; state remained consistent).

---

## 3. Workflow Checkpointing & Restart Evidence

Executed in `tests/integration/workflows/test_postgres_checkpointing.py` and `tests/integration/model_gateway/test_workflow_model_integration.py`:
- **Scenario**: Workflow interrupted after agent step execution.
- **Verification**:
  - State persisted to PostgreSQL checkpoint tables.
  - New `WorkflowEngine` initialized with no in-memory state.
  - Workflow reloads checkpoint thread state and resumes seamlessly from exact interruption point without re-executing completed stages.
- **Result**: **PASS**.

---

## 4. Human Gate Pause & Resume Evidence

Executed in `tests/integration/gates/test_gate_timeouts.py`:
- **Scenario**: Approval SLA expires on a pending gate.
- **Verification**:
  - Gate state automatically updates to `PAUSED`.
  - Unpause via `POST /api/v1/gates/{id}/resume` returns gate to active review.
- **Result**: **PASS**.

---

## 5. Model Provider Fallback Evidence

Executed in `tests/integration/e2e/test_budget_and_recovery_e2e.py`:
- **Scenario**: Primary provider fails with simulated HTTP 503 outage.
- **Verification**:
  - Gateway catches failure, inspects agent `ModelPolicy`.
  - Routes request to `fallback-mock`.
  - Fallback succeeds, spend is reconciled against primary reservation, and `ModelExecution` logs `is_fallback=True` with `primary_provider="primary-mock"`.
- **Result**: **PASS**.
