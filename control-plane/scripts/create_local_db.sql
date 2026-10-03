-- One-time local setup for ZipZy DBA control plane (PostgreSQL 16+).
-- Run as the postgres superuser. Safe to run more than once.
-- Creates only the login role and empty databases; tables come from `alembic upgrade head`.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'zipzy') THEN
        CREATE ROLE zipzy LOGIN PASSWORD 'zipzy';
    END IF;
END
$$;

SELECT 'CREATE DATABASE zipzy_dba OWNER zipzy ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'zipzy_dba')\gexec

SELECT 'CREATE DATABASE zipzy_dba_test OWNER zipzy ENCODING ''UTF8'' TEMPLATE template0'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'zipzy_dba_test')\gexec