# ADR 0007 — Code fetches the data; specialist agents only analyse it

- **Status:** Accepted (refines ADR 0006)
- **Date:** 2026-11-23

## Context

ADR 0006 described each specialist as a small tool-calling loop (up to 4 tool calls). While
building 5.2 we checked Groq's documentation and reports for `openai/gpt-oss-120b`:

- Groq does not support tool use together with strict structured outputs in one call
  (console.groq.com/docs/structured-outputs).
- There are open reports of `gpt-oss-120b` on Groq ignoring tools or answering in text instead
  of calling them (Groq community; langchain-ai/langchain#34155).

Each specialist's tools are few, fixed and cheap (2–3 collectors of the same datasource).

## Decision

- Code decides which collectors a specialist needs (`NEEDS` in `app/ai/graph.py`), fetches
  them through the connector (reusing statistics up to 5 minutes old) and turns them into facts.
- Each specialist is **one** model call in Groq strict JSON-schema mode: facts in, findings out.
- The orchestrator plans (one call, chat only) and composes the answer (one call).
- No LangGraph checkpointer: a run that needs the person's input ends; the answer starts a new
  run. All state lives in our own tables, created by Alembic migrations.

## Why

1. No dependency on tool calling, the least reliable part of this model on Groq today.
2. Fewer calls: 2–5 per run instead of up to 14, so faster and within the free tier.
3. Fully testable without a model: what the specialist sees is decided by code.
4. Safety is unchanged or better: the model cannot ask for anything, not even an allowed tool.

## Consequences

- A specialist cannot ask a follow-up question of the data within a run; the person can ask a
  follow-up in the conversation, which starts a new run with the context saved.
- Adding a data source for a specialist is a code change (`NEEDS`, `facts.py`), reviewed like
  any other.

## Rejected

- **Model-driven tool calling (ADR 0006 as written):** see Context.
- **LangGraph's Postgres checkpointer for pausing runs:** creates tables outside our migrations.
