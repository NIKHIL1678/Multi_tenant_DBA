# ADR 0006 — Supervisor + specialist agents on LangGraph and Groq

- **Status:** Accepted
- **Date:** 2026-11-23

## Context

Phase 5 adds AI on top of the collectors: explaining problems, answering questions,
suggesting fixes and nightly reports. We must choose how agents are organised, what they
may see and do, and which model they use, within ADR 0005 (read-only by default, writes
only after human approval).

## Decision

- **Orchestration:** one LangGraph graph with an Orchestrator (plan + compose) and
  specialist agents (Health & Monitoring, Query Performance, Schema) that run in parallel,
  each limited to its own read-only tools and at most 4 tool calls.
- **Checking:** a code Verifier — not a model — drops findings without valid evidence and
  strips any proposed SQL outside a per-engine allow-list of index and maintenance
  statements.
- **Visibility:** the model receives statistics, structure and normalized query text only,
  never table rows.
- **Writes:** specialists may *propose* SQL; it becomes an action request that a person
  approves; the connector runs it with a separate fix user only after verifying a
  server-signed, single-use approval bound to the statement hash.
- **Model:** `openai/gpt-oss-120b` on Groq with strict JSON-schema output;
  `openai/gpt-oss-20b` as fallback. Both configurable.

## Why

1. Specialists with small tool sets give shorter prompts, fewer wrong tool calls and a
   clear owner per finding; this matches the agent roster in 03.
2. Safety does not depend on the model behaving: the datasource is fixed by the server,
   tools are allow-listed, SQL is checked by code twice (control plane and connector), and a
   human approves every change.
3. No rows leave the customer, which keeps the promise made to customers and avoids
   sending personal data to an LLM provider.
4. Groq is fast enough for interactive chat; strict JSON output removes most parsing
   failures.

## Consequences

- New tables (`agent_runs`, `findings`, conversations, `action_requests`,
  `action_approvals`, `ai_usage_daily`) and a server signing key.
- The connector gains an executor and an optional fix user; protocol change documented in 06.
- Answers can only be as good as the collectors; questions about row contents are
  refused by design.
- A Groq outage disables AI features but nothing else.

## Rejected

- **Single agent with every tool:** simpler, but longer prompts, weaker routing and no
  clear ownership of findings.
- **Separate "fix" agent:** the specialist that found a problem has the context for its
  fix; a code Verifier checks it more reliably than another model.
- **Sample rows for the model (owner opt-in):** useful for data-quality questions, but not
  needed for health, performance or schema work; can be revisited in a later ADR.
- **AI runs SQL it writes, without approval:** violates ADR 0005.
