# Database Security, Least-Privilege Roles, and Audit Immutability
## Multi-Agent Legacy Code Modernization Platform — Sub-Phase 01.2

This document details the security model, role-based access control (RBAC), audit ledger integrity, and credential management for the platform's PostgreSQL database.

---

## 1. Principle of Least Privilege

The application must **never** connect to PostgreSQL as a superuser or schema owner. Privileges are strictly segregated across three operational roles:

```text
┌─────────────────────────────────────────────────────────────┐
│                      PostgreSQL Cluster                     │
│                                                             │
│   ┌────────────────────┐          ┌──────────────────────┐  │
│   │  modernizer_admin  │          │   modernizer_app     │  │
│   │   (Migration/DDL)  │          │   (API/Runtime DML)  │  │
│   └─────────┬──────────┘          └───────────┬──────────┘  │
│             │ DDL                             │ DML         │
│             ▼                                 ▼             │
│   ┌──────────────────────────────────────────────────────┐  │
│   │ Schema 'public' (Tables, Indexes, Constraints)       │  │
│   │                                                      │  │
│   │  • job, module, artifact, agent_run ... (CRUD)       │  │
│   │  • audit_event (INSERT + SELECT ONLY)                │  │
│   └──────────────────────────────────────────────────────┘  │
│             ▲                                               │
│             │ SELECT Only                                   │
│   ┌─────────┴──────────────┐                                │
│   │  modernizer_readonly   │                                │
│   │  (Monitoring/Auditing) │                                │
│   └────────────────────────┘                                │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Role Definitions & Responsibilities

### 2.1. `modernizer_admin` (Migration & DDL Role)
- **Purpose**: Executes Alembic schema migrations and maintenance.
- **Grants**:
  - `OWNER` of `public` schema.
  - `CREATE`, `ALTER`, `DROP` on all tables, sequences, and types in `public`.
  - Defines `DEFAULT PRIVILEGES` for future objects.
- **Access**: Strictly restricted to CI/CD pipeline migration runners and authorized database administrators.

### 2.2. `modernizer_app` (Application Runtime Role)
- **Purpose**: Used by the FastAPI application runtime and background workers.
- **Grants**:
  - `CONNECT` on the database.
  - `USAGE` on schema `public`.
  - `SELECT`, `INSERT`, `UPDATE`, `DELETE` on transactional tables (`job`, `module`, `module_attempt`, `artifact`, `test_case`, `test_result`, `gate`).
  - `USAGE`, `SELECT` on all sequences.
- **Explicit Restrictions**:
  - **No DDL privileges**: Cannot execute `CREATE TABLE`, `ALTER TABLE`, or `DROP TABLE`.
  - **Audit Event Append-Only**: Explicitly **revoked** `UPDATE`, `DELETE`, and `TRUNCATE` privileges on the `audit_event` table. Only `SELECT` and `INSERT` are granted.

### 2.3. `modernizer_readonly` (Diagnostic & Analytics Role)
- **Purpose**: Used for reporting dashboards, security audits, and external BI tools.
- **Grants**:
  - `CONNECT` on database.
  - `USAGE` on schema `public`.
  - `SELECT` on all tables and sequences.
  - **Zero write privileges**: Cannot execute `INSERT`, `UPDATE`, `DELETE`, or `TRUNCATE`.

---

## 3. Provisioning Script (`01_provision_roles.sql`)

The idempotent role provisioning script is located at:
`backend/scripts/database/01_provision_roles.sql`

### How to Execute in pgAdmin:
1. In pgAdmin, connect as the `postgres` superuser.
2. Select database `modernization_dev` (or `modernization_test`).
3. Open **Tools** -> **Query Tool**.
4. Open file `backend/scripts/database/01_provision_roles.sql` and click **Execute (F5)**.
5. Set passwords for each role:
   ```sql
   ALTER ROLE modernizer_admin WITH PASSWORD 'YOUR_SECURE_ADMIN_PASSWORD';
   ALTER ROLE modernizer_app WITH PASSWORD 'YOUR_SECURE_APP_PASSWORD';
   ALTER ROLE modernizer_readonly WITH PASSWORD 'YOUR_SECURE_READONLY_PASSWORD';
   ```

---

## 4. Credential & TLS Security Invariants

The platform settings system (`Settings`) enforces the following production invariants:

1. **Password Redaction**: `settings.database_url_masked` redacts user passwords from all application logs, error traces, and status endpoints.
2. **Prohibited Dev Credentials**: Default development passwords (`modernizer_dev_pwd`, `modernizer_local_dev_pwd`) are rejected with `ValidationError` when running in `production`.
3. **Prohibited SQLite**: SQLite URLs (`sqlite+aiosqlite://`) are strictly rejected in `production` and `staging`.
4. **Mandatory TLS**: Setting `db_ssl_mode="disable"` in `production` raises a validation error. Production database connections must enforce TLS certificate verification (`require` or `verify-full`).
