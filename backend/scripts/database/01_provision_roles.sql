-- ==============================================================================
-- Multi-Agent Legacy Code Modernization Platform
-- PostgreSQL Role Provisioning & Least-Privilege Access Control
-- Sub-Phase 01.2: Database Persistence & Migration Governance
-- ==============================================================================
--
-- USAGE:
-- Execute this script as a PostgreSQL superuser or database owner:
--   psql -h <host> -p <port> -U postgres -d <dbname> -f 01_provision_roles.sql
--
-- IMPORTANT SECURITY RULES:
-- 1. Passwords MUST be passed via psql variables or changed immediately:
--      psql -v ADMIN_PASSWORD="'<secret>'" -v APP_PASSWORD="'<secret>'" -v READONLY_PASSWORD="'<secret>'" ...
-- 2. Never hardcode production credentials in this script.
-- 3. The application MUST connect using 'modernizer_app', NEVER as superuser or 'modernizer_admin'.
-- ==============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- ------------------------------------------------------------------------------
-- 1. Create Roles (Idempotent Role Definition)
-- ------------------------------------------------------------------------------

DO $$
BEGIN
    -- Migration / DDL Administration Role (Owner of Application Objects)
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'modernizer_admin') THEN
        CREATE ROLE modernizer_admin WITH LOGIN CREATEDB;
    END IF;

    -- Application Runtime Role (DML Only, No DDL, Least Privilege)
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'modernizer_app') THEN
        CREATE ROLE modernizer_app WITH LOGIN NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;

    -- Operational Read-Only Role (Monitoring, Auditing, Diagnostics)
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'modernizer_readonly') THEN
        CREATE ROLE modernizer_readonly WITH LOGIN NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

-- Set secure search path for all roles to prevent search path injection attacks
ALTER ROLE modernizer_admin SET search_path = public;
ALTER ROLE modernizer_app SET search_path = public;
ALTER ROLE modernizer_readonly SET search_path = public;

-- Set connection and statement timeouts for runtime and read-only roles
ALTER ROLE modernizer_app SET statement_timeout = '30000'; -- 30 seconds
ALTER ROLE modernizer_readonly SET statement_timeout = '15000'; -- 15 seconds

-- ------------------------------------------------------------------------------
-- 2. Database & Schema Level Grants
-- ------------------------------------------------------------------------------

-- Revoke default public creation privileges on public schema (PostgreSQL 15+ best practice)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Grant database connection rights via dynamic SQL
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO modernizer_admin, modernizer_app, modernizer_readonly', current_database());
END
$$;

-- Schema usage
GRANT USAGE, CREATE ON SCHEMA public TO modernizer_admin;
GRANT USAGE ON SCHEMA public TO modernizer_app;
GRANT USAGE ON SCHEMA public TO modernizer_readonly;

-- Transfer schema ownership or grant all schema rights to migration admin
ALTER SCHEMA public OWNER TO modernizer_admin;

-- ------------------------------------------------------------------------------
-- 3. Application Runtime Privileges (DML on existing tables)
-- ------------------------------------------------------------------------------

-- Standard operational tables: SELECT, INSERT, UPDATE, DELETE
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO modernizer_app;

-- Strict Audit Event Immutability:
-- modernizer_app is restricted to SELECT and INSERT only on 'audit_event'.
-- UPDATE and DELETE privileges are revoked to enforce append-only ledger integrity.
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE schemaname = 'public' AND tablename = 'audit_event') THEN
        REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_event FROM modernizer_app;
        GRANT SELECT, INSERT ON TABLE audit_event TO modernizer_app;
    END IF;
END
$$;

-- Sequences usage for ID generation
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO modernizer_app;

-- ------------------------------------------------------------------------------
-- 4. Read-Only Operational Privileges
-- ------------------------------------------------------------------------------
GRANT SELECT ON ALL TABLES IN SCHEMA public TO modernizer_readonly;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO modernizer_readonly;

-- ------------------------------------------------------------------------------
-- 5. Default Privileges for Future Tables and Sequences (Created by modernizer_admin)
-- ------------------------------------------------------------------------------

-- Future tables created by modernizer_admin grant standard DML to modernizer_app
ALTER DEFAULT PRIVILEGES FOR ROLE modernizer_admin IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO modernizer_app;

-- Future tables created by modernizer_admin grant SELECT to modernizer_readonly
ALTER DEFAULT PRIVILEGES FOR ROLE modernizer_admin IN SCHEMA public
    GRANT SELECT ON TABLES TO modernizer_readonly;

-- Future sequences created by modernizer_admin
ALTER DEFAULT PRIVILEGES FOR ROLE modernizer_admin IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO modernizer_app;

ALTER DEFAULT PRIVILEGES FOR ROLE modernizer_admin IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO modernizer_readonly;

COMMIT;
