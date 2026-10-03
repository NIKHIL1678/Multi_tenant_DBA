# ADR 0003 — Python + FastAPI for control plane and connector

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

The platform needs mature drivers for many database engines, strong SQL parsing for the
safety guard, and an AI/agent ecosystem. The wider ZipZy stack is Next.js/TypeScript.

## Decision

Use **Python 3.12** for the control plane (**FastAPI**, SQLAlchemy 2 async, Alembic,
Pydantic) and the connector. Use **uv** for dependency management, **ruff** for lint and
format, **mypy** (strict) for types, **pytest** for tests. The dashboard stays in Next.js.

## Why

- Best-in-class async drivers: asyncpg, asyncmy, motor/pymongo, and more.
- Real SQL parsing for the guard (e.g. sqlglot) across dialects.
- Strongest ecosystem for LLM agents and data tooling.
- FastAPI gives typed request/response models and OpenAPI docs for the dashboard.

## Consequences

- Two languages in the company (Python backend, TypeScript frontend).
- API contracts are shared via the generated OpenAPI schema.

## Rejected

- **TypeScript/Node everywhere:** weaker multi-engine drivers and SQL parsing.
- **Go:** great for the connector binary, but slower iteration for agent logic; may be
revisited for the connector later.
