# Database Backup, Restore, and Disaster Recovery
## Multi-Agent Legacy Code Modernization Platform — Sub-Phase 01.2

This document provides tested operational procedures for backing up, restoring, and recovering platform databases.

---

## 1. Backup Strategies

The platform differentiates between two complementary backup paradigms:

1. **Logical Backups (`pg_dump`)**:
   - Used for periodic snapshots, schema migrations verification, local environment seeding, and database version upgrades.
   - Outputs plain SQL or compressed custom-format archives.
2. **Physical Backups & Point-in-Time Recovery (PITR)**:
   - Required for production high availability, disaster recovery, and recovery to specific transactions via Write-Ahead Log (WAL) archiving (e.g., using pgBackRest or cloud managed backups like AWS RDS / GCP Cloud SQL).

---

## 2. Logical Backup Procedures (`pg_dump`)

### Performing a Compressed Consistent Backup
Run `pg_dump` targeting the database using custom directory/binary format:
```bash
# Windows / PowerShell
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" `
    -h localhost `
    -p 5432 `
    -U postgres `
    -F c `
    -b `
    -v `
    -f "backup_modernization_dev_$(Get-Date -Format 'yyyyMMdd_HHmmss').dump" `
    modernization_dev
```

### Performing Schema-Only Backup
To capture only the DDL schema without table contents:
```bash
& "C:\Program Files\PostgreSQL\18\bin\pg_dump.exe" `
    -h localhost `
    -p 5432 `
    -U postgres `
    -s `
    -f "schema_only.sql" `
    modernization_dev
```

---

## 3. Restore Procedures (`pg_restore`)

> [!CAUTION]
> Never restore directly over a production database without verifying authorization and having a tested pre-restore backup snapshot.

### Restoring to a Clean Database
1. Create a clean destination database in pgAdmin or via psql:
   ```sql
   CREATE DATABASE modernization_restored;
   ```
2. Restore using `pg_restore`:
   ```bash
   & "C:\Program Files\PostgreSQL\18\bin\pg_restore.exe" `
       -h localhost `
       -p 5432 `
       -U postgres `
       -d modernization_restored `
       -v `
       "backup_modernization_dev_20261015.dump"
   ```

### Post-Restore Verification
Always verify the integrity of the restored schema:
1. Verify Alembic migration revision matches:
   ```bash
   alembic -x db_url=postgresql+asyncpg://postgres:PWD@localhost:5432/modernization_restored current
   ```
2. Verify all 10 core tables exist:
   ```sql
   SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';
   ```
3. Run the platform readiness probe:
   ```bash
   python -c "import asyncio; from modernization_platform.db.engine import check_database_readiness; print(asyncio.run(check_database_readiness()))"
   ```

---

## 4. Failed Migration Recovery

If a migration fails halfway during deployment:
1. PostgreSQL executes DDL inside transactions, so failed migrations roll back atomically without partial schema states.
2. Inspect the failure in the migration log.
3. Check `SELECT version_num FROM alembic_version;` to verify the active revision.
4. Correct the migration script in source control.
5. Re-run `alembic upgrade head`.
