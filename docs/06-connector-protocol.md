# 06 — Connector & Protocol

## What the connector is

A small program (shipped as a Docker image, `zipzy/connector`) that the customer runs
inside their network, next to their databases. It:

- connects to the customer's databases locally, using credentials from its local config;
- dials **out** to ZipZy over a secure WebSocket and keeps that connection open;
- executes normalized tools through engine adapters and returns normalized results;
- refuses anything that is not allowed by its own local guard.

## Local configuration (`config.yaml`)

```
zipzy:
  server: wss://gateway.zipzy.in
  token: ${ZIPZY_TOKEN}            # one-time enrollment token (first run only)

databases:
  - name: main-postgres
    engine: postgres
    host: 10.0.0.4
    port: 5432
    user: zipzy_readonly
    password: ${PG_PASSWORD}       # read from environment, never written in the file
  - name: orders-mongo
    engine: mongodb
    uri: mongodb://zipzy_ro:${MONGO_PASSWORD}@10.0.0.9:27017
```

The connector can print a ready-made SQL/Mongo script to create a least-privilege
read-only user for each engine.

## Enrollment

1. A member with `connectors.manage` creates a connector in the dashboard.
2. The API returns a one-time **enrollment token** (valid 15 minutes, stored only as a
SHA-256 hash, single use).
3. The customer runs the connector with that token.
4. The connector generates an **Ed25519 key pair**, keeps the private key on local disk
(mounted volume), and sends the token + public key to `POST /v1/connectors/enroll`.
5. The API verifies and burns the token, stores the public key, and returns `connector_id`.

## Session

1. Connector opens `wss://gateway.zipzy.in/v1/connect`.
2. Server sends a random challenge; connector signs it with its private key.
3. Server verifies with the stored public key and checks the connector is not revoked.
4. Connector sends `hello` (software version, protocol version) and
`datasources.report` (per database: engine, version, capability manifest, status).
5. Heartbeat `ping` every 20 s; server marks the connector `offline` after 60 s silence.
6. On disconnect the connector reconnects with exponential backoff and jitter
(1 s doubling to a 60 s cap).

## Messages (JSON-RPC 2.0 over WebSocket)

Direction
Method
Purpose

C → S
`hello`
Versions, signed challenge response

C → S
`datasources.report`
Engine, version, capabilities, status per datasource

C ↔ S
`ping`
Heartbeat

S → C
`invoke`
Run one tool on one datasource

C → S
result / error
JSON-RPC response to `invoke`

S → C
`connector.revoke`
Kill switch: connector stops and deletes its key

`invoke` request:

```
{
  "jsonrpc": "2.0",
  "id": "8f0c…",
  "method": "invoke",
  "params": {
    "datasource": "main-postgres",
    "tool": "get_slow_queries",
    "args": {"limit": 20},
    "timeout_ms": 15000,
    "request_id": "req_…"
  }
}
```

Success: `{"jsonrpc":"2.0","id":"8f0c…","result":{…canonical shape…}}`
Error codes: `-32001` blocked by guard, `-32002` timeout, `-32003` datasource unavailable,
`-32004` unsupported tool for this engine, `-32602` invalid arguments.

Every message carries `protocol_version`; the server rejects incompatible versions with a
clear upgrade message.

## Safety guard (inside the connector)

Engine family
How operations are classified

SQL (PostgreSQL, MySQL, MSSQL)
Parsed with a real SQL parser; each statement classified READ / WRITE / DDL / ADMIN. Multiple statements are each checked.

MongoDB
Allow-list of read commands and aggregation stages; `$out` and `$merge` are writes.

- Only READ is allowed until the approval workflow (Phase 6) exists; then WRITE/DDL are
allowed **only** with a server-signed, single-use approval referencing the exact statement.
- Queries run inside read-only transactions where the engine supports it, with a
statement timeout.
- Results are capped (default 1,000 rows, 5 MB) and configured sensitive columns are redacted.

## Local audit

The connector appends every invocation (time, tool, datasource, statement hash, outcome,
duration) to a local log file, so the customer can independently verify what ZipZy ran.

## Updates

Images are versioned (`1.2.3`, `latest`). The connector logs a notice when the server
reports a newer compatible version.
