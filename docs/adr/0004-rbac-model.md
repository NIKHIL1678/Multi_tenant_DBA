# ADR 0004 — Permission-based RBAC with environment overrides

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

Customers have different people (owner, DBA, IT admin, developers) who need different
access, and access often differs between production and non-production databases.

## Decision

- Fine-grained **permissions**, bundled into **roles**; each member has one tenant-wide role.
- Optional **per-environment role override** for a member.
- Five **system roles** shared by all tenants (`owner`, `dba`, `it_admin`, `backend_dev`,
`viewer`); schema also supports **tenant-custom roles**.
- `metadata.read` is separate from `data.read`.
- The catalog lives in code and is seeded by a migration; a test keeps them in sync.

## Why

- New roles are data, not code.
- Environment overrides cover the most common real-world need (restricted production).
- Separating metadata from row data enables least-privilege operations and privacy compliance.

## Consequences

- Every request resolves permissions (cheap, cacheable per request).
- Role changes require a migration, reviewed like code.

## Rejected

- **Hard-coded role checks** (`if role == "dba"`): brittle, no custom roles.
- **Per-datasource ACLs:** too granular to manage for SMEs; environments cover the need.
