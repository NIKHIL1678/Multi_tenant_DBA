# 02 — Architecture (High-Level Design)

## System context

```
flowchart LR
    subgraph Customer["Customer network"]
        DB1[(PostgreSQL)]
        DB2[(MySQL)]
        DB3[(MongoDB)]
        CONN["ZipZy Connector<br/>(Docker container)"]
        CONN --- DB1
        CONN --- DB2
        CONN --- DB3
    end

    subgraph ZipZy["ZipZy cloud"]
        API["Control Plane API<br/>(FastAPI)"]
        HUB["Connection Hub<br/>(WebSocket)"]
        AGENTS["Agents<br/>(Health, Performance, …)"]
        META[(Metadata DB<br/>PostgreSQL)]
        REDIS[(Redis)]
        API --- META
        HUB --- REDIS
        API --- HUB
        AGENTS --> API
    end

    USER["Dashboard users"] --> API
    CONN -- "outbound WSS (TLS)" --> HUB
```

## Components

Component
Responsibility

**Control Plane API**
Tenants, members, RBAC, connectors, datasources, findings, approvals, audit. Single entry point for the dashboard and agents.

**Connection Hub**
Holds the long-lived WebSocket from each connector; routes invocations to the right connector and returns results.

**Metadata DB**
PostgreSQL. Source of truth for everything except customer data. See [04](https://claude.ai/chat/04-data-model.md).

**Redis**
Routes requests to whichever API instance holds a connector's socket (pub/sub); short-lived caches and rate limits.

**Agents**
LLM-driven specialists. Call normalized tools through the Control Plane; never talk to customer databases directly.

**Connector**
Runs inside the customer network. Holds DB credentials, runs engine adapters, enforces the read-only guard, keeps a local audit log. See [06](https://claude.ai/chat/06-connector-protocol.md).

**Dashboard**
Web UI (Next.js) for members: datasources, findings, approvals, audit.

## Unified gateway

Agents speak one vocabulary regardless of engine:

```
Agent → normalized tool (e.g. get_slow_queries) → Control Plane (policy + audit)
      → Hub → Connector → engine adapter (PostgreSQL | MySQL | MongoDB) → customer DB
```

- **Normalized tools:** `ping`, `server_info`, `list_databases`, `get_schema`,
`get_indexes`, `get_table_stats`, `get_connections`, `get_locks`,
`get_replication_status`, `get_slow_queries`, `explain`, `get_config`,
`get_users_and_privileges`, `get_backup_status`, `run_read_query`.
- **Capability manifest:** each adapter declares which tools and features it supports, so
the orchestrator never plans work an engine cannot do.
- **Canonical result shapes:** `Entity`, `Index`, `QueryStat`, `HealthMetric`, `Finding` —
agents reason over one shape; engine detail stays in adapters and per-engine runbooks.
- **Engine extensions:** optional engine-specific tools (e.g. `pg_stat_statements`,
MongoDB `$indexStats`) so engines keep their strengths.

## Key flows

### Connector enrollment

```
sequenceDiagram
    actor Admin as IT Admin / DBA
    participant API as Control Plane
    participant C as Connector
    Admin->>API: Create connector
    API-->>Admin: One-time enrollment token (15 min)
    Admin->>C: docker run -e ZIPZY_TOKEN=… zipzy/connector
    C->>C: Generate Ed25519 key pair
    C->>API: Enroll(token, public key)
    API->>API: Verify token hash, mark used, store public key
    API-->>C: connector_id
    C->>API: Open WSS, sign challenge
    C->>API: datasources.report (engine, version, capabilities)
```

### Tool invocation (e.g. an agent asks for slow queries)

```
sequenceDiagram
    participant A as Agent
    participant API as Control Plane
    participant H as Hub
    participant C as Connector
    participant DB as Customer DB
    A->>API: invoke(datasource, get_slow_queries)
    API->>API: RBAC + policy check, write audit
    API->>H: route to connector
    H->>C: JSON-RPC invoke
    C->>C: Guard: classify op (READ only)
    C->>DB: engine-specific query
    DB-->>C: rows
    C->>C: Normalize, cap rows/bytes, redact
    C-->>H: result
    H-->>API: result
    API-->>A: canonical result
```

## Security model

Layer
Control

Network
Connector dials out over TLS; no inbound ports on customer side.

Connector identity
Ed25519 key pair; server stores only the public key; challenge-response on every connect.

Credentials
Customer DB credentials live only in the connector's local config/env.

Authorization
RBAC per tenant and environment ([05](https://claude.ai/chat/05-rbac.md)); checked on every request.

Tenant isolation
Application checks + PostgreSQL Row-Level Security (Phase 2).

Operation safety
Read-only guard in control plane **and** connector; DB-level read-only user recommended.

Data minimisation
`metadata.read` separate from `data.read`; row and payload caps; column redaction.

Audit
Every invocation, approval and admin action in `audit_log`; connector keeps its own local log.

Kill switch
Revoking a connector closes its socket and rejects reconnects.

## Deployment (target, AWS)

Piece
Service

Control Plane + Hub
Containers on ECS Fargate behind an Application Load Balancer (WebSocket enabled)

Metadata DB
RDS PostgreSQL 16+ (Multi-AZ in production)

Redis
ElastiCache Redis

Connector image
Public registry (Docker Hub or ECR Public)

Secrets
AWS Secrets Manager

CI/CD
GitHub Actions

## Scaling

- API instances are stateless except for open connector sockets; Redis pub/sub routes each
invocation to the instance that holds the target socket.
- Invocations carry timeouts; connectors enforce concurrency limits per datasource.
- Audit log grows fastest; it is append-only and will be partitioned by month.

## Observability

- Structured JSON logs with `request_id` propagated API → Hub → Connector.
- Health endpoints: `/healthz` (process up), `/readyz` (dependencies up).
- Metrics: connector online count, invocation latency and error rate per tool and engine.
