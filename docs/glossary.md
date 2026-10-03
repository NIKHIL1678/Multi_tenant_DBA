# Glossary

Term
Meaning

**Tenant**
A customer company using ZipZy DBA.

**Member**
A user inside a tenant, with a role.

**Role / Permission**
A role is a bundle of permissions; a permission is one ability.

**Environment**
A group of datasources such as production, staging or dev.

**Connector**
Program running inside the customer network that talks to their databases.

**Datasource**
One customer database reachable through a connector.

**Control plane**
ZipZy's cloud backend (API, hub, metadata DB).

**Hub**
Part of the control plane that holds connector WebSocket connections.

**Adapter**
Engine-specific code in the connector (PostgreSQL, MySQL, MongoDB …).

**Normalized tool**
Engine-independent operation an agent can call, e.g. `get_slow_queries`.

**Capability manifest**
List of tools and features an adapter supports for a datasource.

**Guard**
Connector component that blocks any operation that is not allowed.

**Finding**
An agent's result: what is wrong, impact, and the proposed fix.

**Action**
A proposed change to a database; needs approval before execution.

**WSS**
WebSocket Secure — an encrypted, long-lived two-way connection.

**JSON-RPC**
Simple message format for requests and responses over the WebSocket.

**Migration**
Versioned script (Alembic) that changes the database schema.

**ADR**
Architecture Decision Record — a short note on one design decision.

**RLS**
Row-Level Security — PostgreSQL feature that filters rows per tenant.

**SME / MSME**
Small and Medium Enterprises; in India, Micro, Small and Medium Enterprises.
