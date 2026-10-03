# ADR 0001 — PostgreSQL for the metadata database

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

The control plane stores tenants, users, roles, connectors, datasources and the audit
log. It is multi-tenant: one tenant must never read another tenant's rows. MySQL was the
initial choice (team familiarity); this ADR replaces it.

## Decision

Use **PostgreSQL 16+** for the control-plane metadata database, accessed from Python via
SQLAlchemy 2 (async) + **asyncpg**, with schema managed only by **Alembic** migrations.

## Why

- **Row-Level Security:** the database itself can enforce tenant isolation as a second
line of defence behind application checks.
- **Native `UUID`, `TIMESTAMPTZ`, `JSONB`, `CITEXT`, `INET`:** correct types instead of
workarounds.
- **`UNIQUE NULLS NOT DISTINCT`:** system roles (tenant_id NULL) are unique without tricks.
- **Transactional DDL:** a failed migration rolls back completely.
- **JSONB + GIN indexes:** efficient queries over capabilities and audit details.
- Fully supported on AWS RDS / Aurora.

## Consequences

- Local development needs PostgreSQL 16+.
- Enum-like columns use `TEXT` + `CHECK` constraints, not native enums.
- Customer databases are unaffected: the connector still supports MySQL, MongoDB, etc.

## Rejected

- **MySQL 8:** no RLS, non-transactional DDL, weaker type system for our needs.
- **MongoDB:** relational integrity (FKs, unique constraints) is central to RBAC.
