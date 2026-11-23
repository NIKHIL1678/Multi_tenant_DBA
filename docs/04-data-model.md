# 04 — Data Model (Metadata DB, PostgreSQL)

This is the control plane's own database. It never stores customer table data.
Schema is created and changed **only** through Alembic migrations.

## Conventions

Item
Rule

Engine
PostgreSQL 16+

Primary keys
`UUID`, default `gen_random_uuid()` (audit log uses `BIGINT` identity)

Timestamps
`TIMESTAMPTZ`, stored in UTC; `created_at` default `now()`; `updated_at` set on every update

Enum-like columns
`TEXT` + `CHECK (col IN (…))` — cheap to evolve, no `ALTER TYPE`

Case-insensitive text
`CITEXT` for emails and slugs (`citext` extension)

JSON
`JSONB`

Constraint names
`pk_<table>`, `fk_<table>_<column>_<ref_table>`, `uq_<table>_<columns>`, `ix_<table>_<columns>`, `ck_<table>_<name>`

Secrets
Tokens are never stored raw — only SHA-256 hashes

## Entity relationships

```
erDiagram
    tenants ||--o{ tenant_members : has
    users ||--o{ tenant_members : joins
    roles ||--o{ tenant_members : "default role"
    tenants ||--o{ roles : "custom roles"
    roles ||--o{ role_permissions : grants
    permissions ||--o{ role_permissions : in
    tenants ||--o{ environments : has
    tenant_members ||--o{ member_environment_roles : overrides
    environments ||--o{ member_environment_roles : scoped
    roles ||--o{ member_environment_roles : uses
    tenants ||--o{ invitations : sends
    tenants ||--o{ connectors : owns
    connectors ||--o{ enrollment_tokens : enrolls
    connectors ||--o{ datasources : exposes
    environments ||--o{ datasources : groups
```

## Tables

### tenants — a customer company

Column
Type
Notes

id
UUID PK

name
TEXT NOT NULL
≤ 150 chars

slug
CITEXT NOT NULL UNIQUE
URL-safe, ≤ 60 chars

plan
TEXT NOT NULL
`free` | `starter` | `growth` | `enterprise`, default `free`

status
TEXT NOT NULL
`active` | `suspended` | `deleted`, default `active`

created_at, updated_at
TIMESTAMPTZ

### users — a person (global, can join many tenants)

Column
Type
Notes

id
UUID PK

email
CITEXT NOT NULL UNIQUE

full_name
TEXT

auth_provider
TEXT NOT NULL
`zipzy_accounts` | `google` | `password`

external_id
TEXT
ID at the auth provider; UNIQUE with `auth_provider`

status
TEXT NOT NULL
`active` | `disabled`

created_at, updated_at
TIMESTAMPTZ

### permissions — catalog of abilities (seeded)

Column
Type
Notes

key
TEXT PK
e.g. `data.read`

description
TEXT

### roles — bundle of permissions

Column
Type
Notes

id
UUID PK
System roles have fixed, deterministic IDs

tenant_id
UUID NULL FK → tenants
NULL = system role shared by all tenants

key
TEXT NOT NULL
e.g. `dba`

name
TEXT NOT NULL
Display name

is_system
BOOLEAN NOT NULL
default false

created_at
TIMESTAMPTZ

Unique: `(tenant_id, key)` with **NULLS NOT DISTINCT**, so system role keys are unique too.

### role_permissions

Column
Type
Notes

role_id
UUID FK → roles ON DELETE CASCADE
PK part

permission_key
TEXT FK → permissions
PK part

### tenant_members — a user's membership in a tenant

Column
Type
Notes

id
UUID PK

tenant_id
UUID FK → tenants

user_id
UUID FK → users

role_id
UUID FK → roles
Tenant-wide default role; must be a system role or a role of the same tenant

status
TEXT NOT NULL
`active` | `suspended`

invited_by
UUID NULL FK → users

joined_at, updated_at
TIMESTAMPTZ

Unique `(tenant_id, user_id)`; index `(user_id)`.

### invitations

Column
Type
Notes

id
UUID PK

tenant_id
UUID FK → tenants

email
CITEXT NOT NULL

role_id
UUID FK → roles
Role granted on acceptance

token_hash
TEXT NOT NULL UNIQUE
SHA-256 hex of the invite token

invited_by
UUID FK → users

expires_at
TIMESTAMPTZ NOT NULL

accepted_at, revoked_at
TIMESTAMPTZ NULL

created_at
TIMESTAMPTZ

Index `(tenant_id, email)`.

### environments — production, staging, dev …

Column
Type
Notes

id
UUID PK

tenant_id
UUID FK → tenants

name
TEXT NOT NULL
UNIQUE per tenant

is_production
BOOLEAN NOT NULL
default false

created_at
TIMESTAMPTZ

### member_environment_roles — per-environment role override

Column
Type
Notes

member_id
UUID FK → tenant_members ON DELETE CASCADE
PK part

environment_id
UUID FK → environments ON DELETE CASCADE
PK part

role_id
UUID FK → roles
Role used inside this environment

### connectors — program running in the customer network

Column
Type
Notes

id
UUID PK

tenant_id
UUID FK → tenants

name
TEXT NOT NULL
UNIQUE per tenant

public_key
TEXT NULL
Ed25519 public key, set at enrollment

status
TEXT NOT NULL
`pending` | `online` | `offline` | `revoked`

version
TEXT NULL
Connector software version

last_seen_at, revoked_at
TIMESTAMPTZ NULL

created_by
UUID FK → users

created_at, updated_at
TIMESTAMPTZ

### enrollment_tokens — one-time tokens to enroll a connector

Column
Type
Notes

id
UUID PK

connector_id
UUID FK → connectors ON DELETE CASCADE

token_hash
TEXT NOT NULL UNIQUE
SHA-256 hex

expires_at
TIMESTAMPTZ NOT NULL
15 minutes after creation

used_at
TIMESTAMPTZ NULL
Single use

created_by
UUID FK → users

created_at
TIMESTAMPTZ

### datasources — a customer database reachable through a connector

Column
Type
Notes

id
UUID PK

tenant_id
UUID FK → tenants

connector_id
UUID FK → connectors

environment_id
UUID FK → environments

local_name
TEXT NOT NULL
Name from connector config, e.g. `main-mysql`; UNIQUE per connector

engine
TEXT NOT NULL
`postgres` | `mysql` | `mariadb` | `mongodb` | `mssql`

version
TEXT NULL

capabilities
JSONB NULL
Capability manifest reported by the adapter

status
TEXT NOT NULL
`unknown` | `connected` | `error`

last_checked_at
TIMESTAMPTZ NULL

created_at, updated_at
TIMESTAMPTZ

Index `(tenant_id, environment_id)`.

### snapshots — what collectors found on a datasource

One row per collector run: statistics and metadata only, never table rows. Removed with
the datasource.

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID FK → tenants | |
| datasource_id | UUID FK → datasources ON DELETE CASCADE | |
| collector | TEXT NOT NULL | `health` \| `table_stats` \| `indexes` \| `slow_queries` \| `locks` \| `table_index` (CHECK) |
| data | JSONB NOT NULL | The connector's answer after validation (`app/schemas/snapshots.py`) |
| collected_at | TIMESTAMPTZ NOT NULL | |

Index `(datasource_id, collector, collected_at)`. Rows older than 30 days are deleted when a
new one is stored; `table_index` keeps only its latest row (it can be a few MB). A collector
that ran less than 30 s ago (10 min for `table_index`) is not asked again.
Migrations: 0005 (table), 0006 (`slow_queries`, `locks`, `table_index`).

### AI agents (migration 0007)

Every row has `tenant_id`; rows go with their datasource (ON DELETE CASCADE). No customer
table rows are stored: only statistics, structure, normalized statement text and what the
agents wrote about them. See [08 AI agents](08-ai-agents.md).

**ai_conversations** — one person's chat about one datasource

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id | UUID FK → tenants | |
| datasource_id | UUID FK → datasources ON DELETE CASCADE | |
| user_id | UUID FK → users | Private to this person |
| title | TEXT NOT NULL | First question or the explained problem |
| context | JSONB NOT NULL DEFAULT '{}' | What it is about: `{"table": "hrm.attendance_*", "period": "2026-11"}` |
| created_at, updated_at | TIMESTAMPTZ | |

Index `(datasource_id, user_id, updated_at)`.

**ai_messages** — `id`, `tenant_id`, `conversation_id` (FK ON DELETE CASCADE), `role`
(`user` \| `assistant`, CHECK), `content` TEXT, `run_id` (FK → agent_runs ON DELETE SET NULL),
`created_at`. Index `(conversation_id, created_at)`.

**agent_runs** — one run of the agent graph

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id, datasource_id, user_id, conversation_id | UUID FKs | datasource and conversation ON DELETE CASCADE |
| kind | TEXT | `chat` \| `explain` (CHECK) |
| status | TEXT | `queued` \| `running` \| `done` \| `needs_input` \| `failed` (CHECK) |
| question | TEXT | What the agents were asked |
| problem | TEXT NULL | Explain: the problem id from the server page |
| steps | JSONB | Progress shown while it runs: `[{key, label}]` |
| answer | TEXT NULL | The reply |
| follow_ups | JSONB | Up to 3 suggested next questions |
| clarification | JSONB NULL | `{question, options: [{label, table}]}` when it ended asking |
| notes | JSONB | What could not be checked, and why |
| error | TEXT NULL | Why it failed, in words a person can act on |
| model | TEXT NULL | Model(s) that answered |
| input_tokens, output_tokens | INTEGER | As reported by Groq |
| created_at, finished_at | TIMESTAMPTZ | |

Indexes `(user_id, status)` (one active run per person) and `(datasource_id, created_at)`.

**findings** — verified findings of a run

| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| tenant_id, datasource_id, run_id | UUID FKs | datasource and run ON DELETE CASCADE |
| specialist | TEXT | `health` \| `query` \| `schema` |
| severity | TEXT | `high` \| `medium` \| `low` (CHECK) |
| category | TEXT | e.g. `missing_index`, `duplicate_index`, `lock_wait` |
| title, explanation | TEXT | |
| evidence | JSONB | `[{id: "Q1", summary: "…"}]`, every id checked to exist |
| table_name | TEXT NULL | `schema.table`, checked to exist |
| action | JSONB NULL | Suggested statement that passed the allow-list: `{kind, statement, table, reason, risk}` |
| fingerprint | TEXT | Same problem across runs (category + table) |
| status | TEXT | `open` \| `resolved` \| `dismissed` (CHECK), default `open` |
| created_at | TIMESTAMPTZ | |

Indexes `(datasource_id, status, created_at)` and `(run_id)`.

**ai_usage_daily** — `(tenant_id, day)` PK, `runs`, `input_tokens`, `output_tokens`: for the
daily limits (`AI_DAILY_RUNS`, `AI_DAILY_TOKENS`).

### audit_log — append-only record of everything

Column
Type
Notes

id
BIGINT identity PK

tenant_id
UUID NOT NULL
No FK on purpose — audit outlives the rows it describes

actor_type
TEXT NOT NULL
`user` | `agent` | `connector` | `system`

actor_id
UUID NULL

action
TEXT NOT NULL
e.g. `datasource.query`, `member.invite`

target_type
TEXT NULL

target_id
UUID NULL

details
JSONB NULL
Never contains secrets or row data

ip_address
INET NULL

request_id
TEXT NULL
Correlates API → Hub → Connector

created_at
TIMESTAMPTZ

Indexes: `(tenant_id, created_at)`, `(tenant_id, actor_id, created_at)`,
`(target_type, target_id)`. The application's DB role has no `UPDATE`/`DELETE` on this table.
Partition by month once volume requires it.

## Seed data (migration)

- 11 permissions and 5 system roles with their mappings — see [05 RBAC](https://claude.ai/chat/05-rbac.md).
- Seed values are frozen inside the migration; a test asserts they match the application catalog.

## Tenant isolation (Phase 2)

Every tenant-scoped table gets a PostgreSQL Row-Level Security policy:
`tenant_id = current_setting('app.tenant_id')::uuid`. The API sets `app.tenant_id` with
`SET LOCAL` at the start of each request transaction. Migrations run as the owner role,
which bypasses RLS; the application connects as a separate, non-owner role.

## Planned tables (later phases)

`findings`, `action_requests`, `action_approvals`, `invocations`, `agent_runs`,
`schedules`, `alerts` — added by migrations when their phase starts, and documented here.
