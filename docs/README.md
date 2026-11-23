# ZipZy DBA — Documentation

Multi-tenant, multi-agent DBA platform for SMEs. Customers connect any database
(PostgreSQL, MySQL, MongoDB, …) through a connector that runs inside their network;
specialist AI agents monitor, diagnose and recommend fixes.

| Doc | What it covers |
|---|---|
| [01 Overview](01-overview.md) | Problem, users, principles, scope, phases |
| [02 Architecture (HLD)](02-architecture-hld.md) | Components, data flow, security model, deployment |
| [03 DBA capabilities](03-dba-capabilities.md) | Every DBA task and which agent owns it |
| [04 Data model](04-data-model.md) | Metadata database (PostgreSQL) tables and relations |
| [05 RBAC](05-rbac.md) | Roles, permissions, environment overrides |
| [06 Connector protocol](06-connector-protocol.md) | Enrollment, tunnel, messages, safety guard |
| [07 Dev workflow](07-dev-workflow.md) | Branching, migrations, tests, CI, local setup |
| [08 AI agents](08-ai-agents.md) | Agent graph, tools, evidence checks, fix approval, build order |
| [Glossary](glossary.md) | Terms used across the docs |

## Architecture Decision Records (ADRs)

An ADR records one significant decision: the context, what we chose, why, and what we
rejected. ADRs are never edited after acceptance; a new ADR supersedes an old one.

| # | Decision | Status |
|---|---|---|
| [0001](adr/0001-postgresql-metadata-db.md) | PostgreSQL for the metadata database | Accepted |
| [0002](adr/0002-outbound-connector.md) | Customer-side connector with outbound tunnel | Accepted |
| [0003](adr/0003-python-fastapi.md) | Python + FastAPI for control plane and connector | Accepted |
| [0004](adr/0004-rbac-model.md) | Permission-based RBAC with environment overrides | Accepted |
| [0005](adr/0005-read-only-by-default.md) | Read-only by default; writes need human approval | Accepted |
| [0006](adr/0006-ai-orchestration.md) | Supervisor + specialist agents on LangGraph and Groq | Accepted |
| [0007](adr/0007-code-fetches-ai-analyses.md) | Code fetches the data; specialist agents only analyse it | Accepted |

New significant decision → copy [adr/0000-template.md](adr/0000-template.md).

## Keeping docs current

- Docs change in the same PR as the code they describe.
- A PR that changes schema, permissions or the connector protocol must update
  04, 05 or 06 respectively.
