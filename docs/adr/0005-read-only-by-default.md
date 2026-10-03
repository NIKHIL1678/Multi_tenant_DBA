# ADR 0005 — Read-only by default; writes need human approval

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

Agents are LLM-driven and can be wrong or manipulated (prompt injection via data they
read). A bad write on a customer's production database could end their business and ours.

## Decision

- All tools are **read-only** until the approval workflow exists.
- Afterwards, any write goes through **request → approve → execute**, with the approval
bound to the exact statement and verified by the connector.
- In production environments the approver must differ from the requester.
- Autonomous execution is limited to an explicit, per-tenant, opt-in allow-list of safe
operations, and is not part of the initial phases.

## Why

- Worst-case damage from an agent mistake is bounded to reading metadata.
- Customers can adopt the product without trusting AI with writes.

## Consequences

- Some fixes are slower because a human is in the loop.
- The connector must verify server-signed approvals, not just trust the server.

## Rejected

- **Autonomous remediation from day one:** unacceptable risk for early trust.
