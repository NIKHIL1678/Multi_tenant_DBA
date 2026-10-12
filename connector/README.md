# ZipZy DBA — connector

The program each company runs **inside its own network**. It reaches the databases listed in
`connector.yaml` with a read-only monitoring user and only ever connects **out** to ZipZy.
Database passwords never leave the server it runs on.

## How it works

1. **Enrol (first start only).** It creates its own Ed25519 key pair, sends the *public* key with
   the one-time token from the install command, and saves its identity in `/data/identity.json`
   (mode 600). Later starts reuse it; the token is no longer needed.
2. **Probe.** For each database: connect in a **read-only session**, read the version and a few
   capabilities (for example whether the user is least-privilege). It never reads table rows.
3. **Stay connected.** It opens ONE outbound WebSocket to ZipZy, signs a fresh challenge with
   its key, and reports its databases (they appear in ZipZy by themselves). It answers ZipZy's
   pings, re-checks every database every 5 minutes, and runs **allow-listed, read-only tools**
   on request (today: `probe`). Nothing can make it run SQL sent from outside.
4. **Reconnect** by itself after network trouble or a ZipZy restart (1 s → 60 s pauses). It stops
   only when the connector is **revoked** in ZipZy or its key is refused (exit code 2).
## Create a monitoring user

PostgreSQL:
```sql
CREATE ROLE zipzy_monitor LOGIN PASSWORD '...';
GRANT pg_monitor TO zipzy_monitor;
-- optional, for slow-query analysis:  CREATE EXTENSION pg_stat_statements;
```

MySQL / MariaDB:
```sql
CREATE USER 'zipzy_monitor'@'%' IDENTIFIED BY '...';
GRANT PROCESS, REPLICATION CLIENT ON *.* TO 'zipzy_monitor'@'%';
GRANT SELECT ON performance_schema.* TO 'zipzy_monitor'@'%';
```

The connector also opens every session as read-only, so even a too-powerful user cannot change
data through it; `check` warns when the user has write rights.

## Commands

```
zipzy-connector check   # test every database from this server (no ZipZy needed); exit 1 if one fails
zipzy-connector run     # enrol on first start, then stay connected to ZipZy (the Docker default)
```

## Environment

| Variable | Set by | Meaning |
|---|---|---|
| `ZIPZY_URL` | install command | ZipZy address |
| `ZIPZY_ENROLL_TOKEN` | install command | one-time enrolment token (first start only) |
| `ZIPZY_CONFIG` | image | settings file, default `/config/connector.yaml` |
| `ZIPZY_DATA_DIR` | image | identity storage, default `/data` (keep it on a volume) |
| your `password_env` names | you | database passwords |

## Develop

```
uv sync
uv run ruff format --check . && uv run ruff check . && uv run mypy . && uv run pytest -q
```

Database tests need a Postgres and a MySQL with the monitoring users above; they are skipped
unless these are set (CI sets them):

```
TEST_PG_HOST TEST_PG_DB TEST_PG_MONITOR_USER TEST_PG_MONITOR_PASSWORD TEST_PG_ADMIN_USER TEST_PG_ADMIN_PASSWORD
TEST_MYSQL_HOST TEST_MYSQL_MONITOR_USER TEST_MYSQL_MONITOR_PASSWORD TEST_MYSQL_ADMIN_USER TEST_MYSQL_ADMIN_PASSWORD
```