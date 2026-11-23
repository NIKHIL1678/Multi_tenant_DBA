# ZipZy DBA — connector

The program each company runs **inside its own network**. It reaches the databases listed in
`connector.yaml` with a read-only monitoring user and only ever connects **out** to ZipZy.
Database passwords never leave the server it runs on.

## How it works

1. **Enrol (first start only).** It creates its own Ed25519 key pair, sends the *public* key with
   the one-time token from the install command, and saves its identity in `/data/identity.json`
   (mode 600). Later starts reuse it; the token is no longer needed.
2. **Probe.** For each database: connect in a **read-only session**, read the version, a few
   capabilities (for example whether the user is least-privilege) and the **catalog**: every
   database on that server with its size and table count. It never reads table rows.
3. **Stay connected.** It opens ONE outbound WebSocket to ZipZy, signs a fresh challenge with
   its key, and reports its databases (they appear in ZipZy by themselves). It answers ZipZy's
   pings, re-checks every database every 5 minutes, and runs **allow-listed, read-only tools**
   on request. Nothing can make it run SQL sent from outside.
4. **Reconnect** by itself after network trouble or a ZipZy restart (1 s → 60 s pauses). It stops
   only when the connector is **revoked** in ZipZy or its key is refused (exit code 2).

## Tools ZipZy may ask for

Each is a fixed, read-only set of queries with a 5 s limit per statement and 30 s overall. None
reads table rows, and every answer has a size limit.

| Tool | Answers | Reads |
|---|---|---|
| `probe` | reachable? version, capabilities, databases on the server | version, grants, catalog |
| `health` | is the server OK? connections, cache hit rate, replication lag | server status counters, a few settings |
| `table_stats` | biggest tables: rows, data and index size, scans, primary key | table statistics |
| `indexes` | unused, duplicate and missing indexes; tables without a primary key; heavy full scans | index definitions and usage counters |
| `slow_queries` | the 20 statements that took the most time: calls, average and worst time, rows read | statement statistics, with every value replaced by `?` / `$1` |
| `locks` | who is waiting for a lock and who holds it; transactions open longer than 60 s | session ids, users, tables, timings (never the statements) |
| `table_index` | every table's name, rows and size, biggest first (up to 50,000), to find one among thousands | table catalog |

`slow_queries` and `locks` never send statement text with values in it: MySQL and
`pg_stat_statements` store statements with every literal replaced, utility statements (which may
keep literals) are skipped, and `locks` reads no statement text at all. When the server cannot
answer (performance_schema off, `pg_stat_statements` missing, MariaDB without lock tables) the
tool says why instead of failing.

Usage counters start again when the database server restarts, so "unused" means "not used since
then". On Postgres, table and index details cover the database named in `connector.yaml`.

## Windows: one file, no setup

For a desktop or laptop next to the database, there is a single `zipzy-connector.exe`:

1. In ZipZy: **Connectors > Add connector**, then download the file and copy the **connection
   code** (it holds this ZipZy's address and the one-time token).
2. Double-click the file and paste the code. It asks MySQL or PostgreSQL, where the database is and
   the monitoring user's password, tests it, registers this computer and connects.
3. Keep the window open. Later starts skip the questions.

Everything is saved for the current Windows user in `%LOCALAPPDATA%\ZipZyConnector` (delete that
folder to start over). Build the file with `scripts\build-windows.ps1` (PyInstaller); it is copied
to `dashboard/public/downloads/`, from where the dashboard offers it.

## Create a monitoring user

PostgreSQL:
```sql
CREATE ROLE zipzy_monitor LOGIN PASSWORD '...';
GRANT pg_monitor TO zipzy_monitor;
```

For slow queries on PostgreSQL, also add `pg_stat_statements` to `shared_preload_libraries`,
restart, and run `CREATE EXTENSION pg_stat_statements;` in the database named in
`connector.yaml` (`pg_monitor` already lets the monitoring user read it).

MySQL / MariaDB:
```sql
CREATE USER 'zipzy_monitor'@'%' IDENTIFIED BY '...';
GRANT PROCESS, REPLICATION CLIENT, SHOW DATABASES, SHOW VIEW ON *.* TO 'zipzy_monitor'@'%';
GRANT SELECT ON performance_schema.* TO 'zipzy_monitor'@'%';
```

What each grant allows (none of them reads or changes table rows):

| Grant | Lets ZipZy see |
|---|---|
| `PROCESS` | open transactions and lock waits |
| `REPLICATION CLIENT` | replication status |
| `SHOW DATABASES` | the name of every database on the server |
| `SHOW VIEW` | table sizes and indexes (and view definitions) |
| `SELECT ON performance_schema.*` | query statistics (slow queries) |

If the server also has a `'zipzy_monitor'@'localhost'` account, give it the same grants: MySQL
uses the most specific account for local connections.

The connector also opens every session as read-only, so even a too-powerful user cannot change
data through it; `check` warns when the user has write rights.

## Commands

```
zipzy-connector check   # test every database from this server (no ZipZy needed); exit 1 if one fails
zipzy-connector run     # enrol on first start, then stay connected to ZipZy (the Docker default)
zipzy-connector start   # desktop: guided first start, then connect (the .exe without arguments)
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
