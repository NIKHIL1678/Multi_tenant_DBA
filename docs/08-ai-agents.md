# 08 — AI Agents (Phase 5)

How the AI layer works: which agents exist, what they may see and do, how a fix goes from
an AI suggestion to a change on the customer's database, and the order we build it in.
Decisions behind it: [ADR 0006](adr/0006-ai-orchestration.md). Safety rules it must keep:
[ADR 0005](adr/0005-read-only-by-default.md).

## What the AI does

| Feature | Trigger | Output |
|---|---|---|
| **Explain** | "Explain" on a problem in *Needs attention* | Plain-language cause, impact and fix for that one problem |
| **Ask AI** | A question in the chat panel on a server page | Answer with the evidence it used, plus suggested fixes |
| **Suggest fixes** | Any run that finds something fixable | Pending *actions* (exact SQL) that a person approves |
| **Reports** | Nightly per server, or "Generate now" | Health report: what changed, top problems, suggested fixes |

All four run the same agent graph; only the entry point and the final format differ.

## Non-negotiable rules

1. **The AI never touches a database.** It calls named tools; the control plane runs them
   through the connector. The datasource is fixed by the server for the run — the model
   cannot choose or change it.
2. **The AI sees statistics and structure only, never rows.** Tool results are health
   numbers, table/index metadata and *normalized* query text (MySQL digests and
   `pg_stat_statements` replace literal values with `?` / `$1`).
3. **The AI cannot write.** It can only *propose* an action. Code (not the model) checks it,
   a person approves it, and the connector verifies a server signature before running it.
4. **Every claim needs evidence.** Findings must cite facts returned by tools; findings that
   cite nothing, or cite facts that do not exist, are dropped before anyone sees them.
5. **The product works without AI.** If Groq is down or the tenant is over its limit, the
   dashboard and collectors keep working; AI features show "unavailable".

## Agents

| Agent | Kind | Tools | Owns |
|---|---|---|---|
| **Orchestrator** | LLM | none | Plans which specialists to ask; writes the final answer |
| **Health & Monitoring** | LLM | `health`, `locks` | Connections, cache, uptime, lock waits |
| **Query Performance** | LLM | `slow_queries`, `table_stats`, `indexes` | Slow/full-scan queries, missing indexes |
| **Schema** | LLM | `table_stats`, `indexes`, `list_databases` | Primary keys, duplicate/unused indexes, big tables |
| **Verifier** | code | — | Evidence check, SQL allow-list, object existence |
| **Ops Executor** | code | — | Runs *approved* actions through the connector |

Specialists may attach a proposed action to a finding. There is no separate "fix" agent:
the specialist that found the problem knows the fix best, and the Verifier checks it.

## The graph (LangGraph)

```mermaid
flowchart TD
    IN(["Explain / question"]) --> PLAN["plan: Orchestrator model, or the problem for Explain"]
    PLAN -->|"off-topic or rows asked"| END1(["short answer"])
    PLAN --> RES["resolve: find the table (code)"]
    RES -->|"two equal matches"| END2(["Which table? with buttons"])
    RES --> GAT["gather: statistics to facts (code)"]
    GAT -->|"Send, in parallel"| H["Health agent"]
    GAT --> Q["Query Performance agent"]
    GAT --> S["Schema agent"]
    H --> V["verify (code)"]
    Q --> V
    S --> V
    V --> C["compose: Orchestrator model"]
    C --> OUT(["Answer, verified findings, suggested SQL"])
```

- **plan** — chat: one model call returns the message's **intent**, one of `database`,
  `row_data` (values inside tables: answered with what the agents can and cannot see),
  `greeting` (a short hello with example questions) or `other`; then for `database` the
  specialists (1–3), the words naming a table and a period. One choice instead of two yes/no
  fields, so a row-data question is never mistaken for an off-topic one.
  *Explain* makes no call: the problem decides the specialists (`app/ai/problems.py`).
- **resolve** — `find_tables` (code). Two equally good matches end the run as `needs_input`
  with the tables as buttons; the person's choice starts the next run with the same question
  and the table saved in the conversation. A table the conversation already chose is reused.
- **gather** — code asks the connector for each needed collector older than 5 minutes (stored
  ones if it is offline, with how old they are) and turns them into facts.
- **specialists** — **one model call each, facts in, findings out** (strict JSON). The model
  never calls tools: code fetched the data ([ADR 0007](adr/0007-code-fetches-ai-analyses.md)).
  One failing specialist gives a partial answer; all failing fails the run.
- **verify** — pure Python, see below.
- **compose** — one model call turns verified findings and notes into the reply.

No LangGraph checkpointer is used: a run that needs input *ends*, and the answer starts a new
run, so all state lives in our own tables (managed by Alembic).

### Run state

```python
class RunState(TypedDict, total=False):
    kind: str                      # chat | explain
    question: str
    engine: str                    # the datasource is fixed in the toolbox, never in state
    history: list[dict]            # last 10 messages of the conversation
    context: dict                  # {"table": "hrm.attendance_*", "period": "2026-11"}
    specialists: list[str]
    focus: list[str]               # "schema.table" the question is about
    evidence: Evidence             # facts "H1", "T3", "Q2"… and what exists, for the Verifier
    reports: list[dict]            # specialists' findings (merged from parallel branches)
    verified: list[VerifiedFinding]
    notes: list[str]               # what could not be checked, and why
    answer: str
    clarification: dict | None     # "Which table do you mean?" + options
```

### Facts and evidence

Each tool result is flattened into numbered **facts** before the model sees it, for example
`T3 = {table: "hrm.attendance", rows: 200000, full_scans: 412, has_pk: true}`. Prefixes:
`H` health, `T` tables, `I` indexes, `Q` queries, `L` locks. A finding must list the fact IDs
it relies on:

```json
{
  "severity": "high",
  "category": "missing_index",
  "title": "attendance is read in full 412 times",
  "explanation": "Every lookup by employee and day reads all 200,000 rows …",
  "evidence": ["T3", "Q2"],
  "action": {
    "statement": "CREATE INDEX idx_attendance_emp_day ON hrm.attendance (emp_id, day)",
    "reason": "Lets Q2 read a few rows instead of the whole table",
    "risk": "low"
  }
}
```

### Verifier (code)

A finding survives only if:

1. every evidence ID exists in `facts`;
2. any table, column or index it names exists in the latest snapshot;
3. its action, if any, passes the **action allow-list**: exactly one statement, parsed with
   `sqlglot`, and one of:

| Engine | Allowed |
|---|---|
| MySQL / MariaDB | `CREATE INDEX`, `DROP INDEX`, `ANALYZE TABLE`, `OPTIMIZE TABLE` |
| PostgreSQL | `CREATE INDEX CONCURRENTLY`, `DROP INDEX CONCURRENTLY`, `ANALYZE`, `VACUUM (ANALYZE)`, `REINDEX INDEX CONCURRENTLY` |

Anything else (`UPDATE`, `DELETE`, `DROP TABLE`, `TRUNCATE`, `GRANT`, multi-statement …) is
removed from the finding; the finding itself stays as advice. The connector runs the same
check again before executing (rule 3).

## Tools

Tools are thin wrappers over the collectors that already exist. A tool reuses the latest
snapshot when it is fresh (≤ 5 minutes for AI runs) and otherwise asks the connector to
collect, so the AI and the dashboard always agree on the numbers.

| Tool | Source | Status |
|---|---|---|
| `health` | collector | exists (4.3b) |
| `table_stats` | collector | exists (4.3b) |
| `indexes` | collector | exists (4.3b) |
| `list_databases` | datasource catalog | exists (4.3a) |
| `slow_queries` | MySQL `performance_schema.events_statements_summary_by_digest`; Postgres `pg_stat_statements` (answers *not available* with the reason if missing) | 5.1 |
| `locks` | MySQL `performance_schema.data_lock_waits` + `INNODB_TRX`; Postgres `pg_stat_activity` + `pg_blocking_pids()` | 5.1 |
| `find_tables` | the `table_index` collector (every table's name, rows, size), searched in ZipZy | 5.1 |

Tool output is capped (top 20 queries, 50 lock rows, 25 search results) and passed to the
model as JSON data.
Names that come from the customer database are data, never instructions; the system prompt
says so, and rules 1–3 mean an injected instruction has nothing dangerous to call.

## Finding the right table

A server can have thousands of tables (`attendance_2024_01` … one per month, per branch). The
model never receives the full list. `find_tables(question, schema?, period?)` searches the
latest `table_index` snapshot inside ZipZy (`app/services/table_search.py`):

- **Families:** tables that differ only by a trailing date or number are one result
  (`hrm.attendance_*`, 36 tables, 2024-01 … 2026-12); a dated member carries its period.
- **Matching:** words of the question against words of schema and table names — exact,
  prefix or small typo; words that match no name ("lowest", "employee who …") and time words
  are ignored. Ranked by match, then size.
- **Period:** with `period="2026-11"`, a family lists that month's table and ranks above an
  equal match without one; a missing month returns the nearest earlier table with a note.
- **Ambiguity:** when the top two are about equally good, the result is marked `ambiguous`
  and the agent **asks the person** ("hrm.attendance_* or payroll.attendance?") with the
  options as buttons — it never guesses.
- **Context:** the chosen table is kept in the conversation, so "add an index to it" needs no
  new search; *Explain* passes the exact table and skips the search.

`table_index` lists up to 50,000 tables (biggest first, within one 3 MB message) and is
refreshed at most every 10 minutes; only its latest snapshot is kept.

## From suggestion to change (actions)

```mermaid
sequenceDiagram
    participant AI as Specialist
    participant API as Control plane
    participant U as Approver
    participant C as Connector
    participant DB as Customer DB
    AI->>API: finding + proposed SQL
    API->>API: Verifier (allow-list, objects exist)
    API->>API: action_request = pending
    U->>API: Approve (needs actions.approve)
    U->>API: Run (needs actions.execute)
    API->>C: execute(action) + server signature
    C->>C: verify signature, hash, expiry, single use, allow-list
    C->>DB: run as the fix user
    DB-->>C: ok / error
    C-->>API: result
    API->>API: audit, re-collect indexes, mark finding resolved
```

- **Who can do what** (existing permissions, no new ones): asking and explaining need
  `metadata.read` / `findings.read`; an AI suggestion becomes an action request on behalf of
  the user who asked, so it needs `actions.request` — without it the fix is shown as text
  only. Approving needs `actions.approve`, running needs `actions.execute`.
- **Production environments:** the approver must be a different person from the requester.
  Nightly-report suggestions are requested by `system`.
- **Signed approval:** the control plane signs
  `{action_id, datasource, sha256(statement), expires_at (15 min), nonce}` with its own
  Ed25519 key. The connector learns that public key at enrolment and keeps used nonces, so an
  approval cannot be replayed or reused for different SQL.
- **Fix user:** the connector runs approved actions with a separate database user that has
  only index and maintenance rights. It is optional: a connector without one reports
  `can_execute = false` and the dashboard shows "Copy SQL" instead of "Run".
- **Statuses:** `pending → approved → running → done | failed`, or `rejected` / `expired`
  (not run within 24 h of approval).

## Data model (new tables)

| Table | Purpose |
|---|---|
| `agent_runs` | One row per run: kind, datasource, status, model, tokens in/out, latency, error, step trace (JSONB) |
| `findings` | Verified findings: run, datasource, severity, category, title, explanation, evidence, `fingerprint` (dedupe across runs), status `open / resolved / dismissed` |
| `ai_conversations`, `ai_messages` | Chat history per datasource and user |
| `action_requests` | Proposed change: statement, hash, kind, reason, risk, status, requested by, source finding |
| `action_approvals` | Who approved or rejected, when, and the signed approval issued |
| `ai_usage_daily` | Per-tenant tokens and runs per day, for limits |

Every row carries `tenant_id` and every query filters by it after the API has checked access
(the metadata database does not use row-level security). They are documented in
[04 Data model](04-data-model.md) by the PR that adds them: 5.2 adds `agent_runs`,
`findings`, `ai_conversations`, `ai_messages` and `ai_usage_daily` (migration 0007).

## API

All under `/v1/tenants/{tenant_id}`.

| Method & path | What | PR |
|---|---|---|
| `GET /ai/status` | AI set up?; runs and tokens used today and the limits | 5.2 |
| `POST /datasources/{id}/ai/runs` | Start a run → `202` + run. `{kind: "chat", message, conversation_id?}`, `{kind: "chat", table, conversation_id}` (answer to "Which table?"), `{kind: "explain", problem, problem_title}` | 5.2 |
| `GET /ai/runs/{run_id}` | Status, progress steps, answer, follow-ups, clarification, notes, findings with evidence | 5.2 |
| `GET /ai/conversations` | My conversations about every server I may still ask about, with server name and environment | 5.2b |
| `GET /datasources/{id}/ai/conversations` | My conversations about this datasource | 5.2 |
| `GET /ai/conversations/{id}` | One conversation: messages and its runs | 5.2 |
| `GET /datasources/{id}/actions` · `POST /actions/{id}/approve` · `/reject` · `/execute` | Approval workflow | 5.3 |
| `GET /datasources/{id}/reports` · `POST …/reports` | Reports, generate now | 5.4 |

Errors (stable `code`): `ai_disabled` 503 (no key), `ai_busy` 409 (a run of yours is going),
`ai_limit` 429 (daily allowance used), `unknown_problem` 422. Runs and conversations are
private to the person who started them. Asking needs `metadata.read` **and** `findings.read`
in the datasource's environment. The dashboard polls a running run every second; it works
unchanged through the demo tunnel.

## Model and limits

| Setting | Default |
|---|---|
| `GROQ_API_KEY` | required for AI features; never logged, never sent to the browser |
| `AI_MODEL` | `openai/gpt-oss-120b` (strict JSON-schema output) |
| `AI_FALLBACK_MODEL` | `openai/gpt-oss-20b`, used after the main model failed twice |
| `AI_REASONING_EFFORT` | `medium` |
| `AI_MAX_OUTPUT_TOKENS` | 8192 (reasoning included) |
| `AI_CALL_TIMEOUT_SECONDS` / `AI_RUN_TIMEOUT_SECONDS` | 30 per model call / 90 per run |
| `AI_DAILY_RUNS` / `AI_DAILY_TOKENS` | 50 runs / 200,000 tokens per company per UTC day |

Each model call: main model, main model again, then the fallback, on rate limits, server or
connection errors, timeouts and answers that fail validation; a refused key, unknown model or
other bad request stops at once. The answer is requested in Groq's strict JSON-schema mode
(`app/ai/strict.py`: every property required, nullable = union with null,
`additionalProperties: false`) and validated again with Pydantic, extra fields refused.
One run at a time per person. Runs execute in the API process as background tasks (one API
instance today); runs cut off by a restart are closed at startup. Nightly reports use an
in-process scheduler at 02:00 IST; it moves to a worker if we scale out.

## Dashboard

- **AI Assistant** (sidebar, `/t/{id}/ai`, 5.2b): the main place to chat. Left: my
  conversations across servers and *New chat*; right: the chat. A new chat starts with a server
  picker that remembers the last server (or picks the only one); one server per conversation.
  On phones the list is a picker above the chat. `?c=<conversation>` opens one directly.
- **Server page → Needs attention:** an *Explain* button on each problem.
- **Server page → Ask AI** panel: quick questions about that server, with progress steps and
  evidence chips (`T3`, `Q2`) that show the underlying numbers; *Open in AI Assistant* moves the
  conversation to the full page. Both use the same chat component (`features/ai/chat.tsx`).
- **Server page → Queries** tab: slow queries and lock waits (5.1).
- **Server page → Fixes** tab: actions by status, with Approve / Reject / Run or Copy SQL.
- **Reports** page per server.

## Testing

- `test_ai_llm.py` — the Groq client against a fake Groq API (httpx MockTransport): the exact
  request (model, strict schema, key), retries, fallback, invalid answers, extra fields refused.
- `test_ai_graph.py` — the graph with a **scripted fake model** (no network): routing, Explain
  without planning, "Which table?", follow-ups, made-up evidence and tables dropped, unsafe SQL
  stripped, partial and total failure, names that look like instructions.
- `test_ai_verify.py` — every allowed statement shape per engine and the refused ones
  (other statements, UNIQUE, comments, several statements, unknown tables, columns, indexes).
- `test_ai_api.py` — the real runner, toolbox, Verifier and database with a fake connector
  hub: answers, conversations, Explain, the table choice, offline connector, who may see what,
  limits, and that every problem the dashboard shows can be explained.
- Connector tests for `slow_queries` and `locks` run against real MySQL and PostgreSQL in CI.
- A real Groq run is checked by hand (a key is never in CI).

## Build order

| PR | Scope |
|---|---|
| **5.1** ✅ | Collectors `slow_queries`, `locks`, `table_index` (connector 0.6.0), migration 0006, table search (`find_tables`), Queries tab — everything the agents read, with no model involved yet |
| **5.2** ✅ | Groq client with retry and fallback, AI settings, facts, LangGraph orchestrator + specialists + Verifier, migration 0007 (`agent_runs`, `findings`, conversations, messages, `ai_usage_daily`), Explain buttons and the Ask AI panel |
| **5.3** | `action_requests` + `action_approvals`, server signing key, connector executor and fix user, Fixes tab |
| **5.4** | Nightly reports, Reports page, usage limits shown in Settings |
| **5.5** | *Ask your data* (below) |

## 5.5 — Ask your data (planned)

Questions about rows ("show the attendance of the employee with the lowest attendance") need
the data itself. They get their own mode, built so that **the model writes the query but never
sees the results**:

```
question → find_tables (table + period) → model reads column names only → ONE SELECT
         → Verifier (code) → person sees the SQL and clicks Run
         → connector runs it as the data reader user → results go only to the person's screen
```

- **ZipZy tenant:** fixed by the server for the run (as for every tool); every metadata query
  filters by tenant.
- **The customer's own tenant column** (e.g. `company_id`): when a table has one, the
  Verifier rejects a query without a filter on it; the person picks the value.
- **Size:** at most 12 tables per query, `LIMIT 100`, 5 s timeout, read-only session.
- **Who may run it:** `data.read` in that environment (05 RBAC), **and** the customer's own
  grants to a separate *data reader* database user (they decide which tables or views), **and**
  columns marked hidden in `connector.yaml` are blanked before results leave their network.
- **Not checked by ZipZy:** the customer's application rules (e.g. a manager sees only their
  team); they enforce those with a view granted to the data reader user.
