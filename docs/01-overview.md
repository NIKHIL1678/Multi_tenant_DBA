# 01 — Overview

## Problem

Small and medium enterprises (SMEs) typically run 1–5 production databases but rarely
have a dedicated DBA. A developer or IT person looks after the database on the side.
Result: slow queries go unnoticed, backups are never tested, access is over-privileged,
and outages are diagnosed late.

## Product

An AI DBA team as a service:

- The customer installs a small **connector** inside their network with one command.
- The connector reaches their databases locally and dials **out** to ZipZy — no firewall
changes, and database credentials never leave the customer's network.
- **Specialist agents** (health, performance, backup, security, …) inspect the databases
through a **unified gateway** and report findings in plain language.
- Any change to a database requires a human with the right role to approve it.

## Users

Persona
Needs

Owner / founder
Confidence the data is safe; cost visibility

DBA (in-house or freelance)
Full diagnostic power; approve and run fixes

IT admin
Set up connectors and people; must not see customer data

Backend developer
Understand slow queries; propose fixes

Viewer
Read health and reports

One person can belong to several tenants (e.g. a freelance DBA serving three companies)
with a different role in each.

## Principles

1. **Read-only by default.** Writes are proposals until approved by an authorised person.
2. **Defense in depth.** Safety checks run in the control plane *and* again in the connector.
3. **Credentials stay with the customer.**
4. **Engine-agnostic.** Agents use normalized tools; engine specifics live in adapters.
5. **Everything is audited.** Every query, approval and action is logged.
6. **No manual changes.** Schema via migrations, code via PRs, deploys via CI.
7. **Plain language.** Users are often not DBAs; findings explain impact and the fix.

## Supported engines (customer side)

Engine
Target phase

PostgreSQL
Phase 3

MySQL / MariaDB
Phase 3

MongoDB
Phase 3

Microsoft SQL Server
Later

Redis
Later

## Phases

Phase
Scope
Status

1
Control plane skeleton: metadata schema, RBAC, audit, CI
In progress

2
Auth via ZipZy Accounts; tenant, member, invitation APIs; row-level security
Planned

3
Connector + unified gateway (read-only tools) for PostgreSQL, MySQL, MongoDB
Planned

4
First agent: Health & Monitoring
Planned

5
Query Performance agent
Planned

6
Action approval workflow (request → approve → execute)
Planned

7+
Backup & Recovery, Security & Compliance, Schema & Migration, Capacity & Cost agents
Planned

## Out of scope (for now)

- Provisioning or installing database servers for customers.
- Autonomous writes without human approval.
- Storing customer database credentials in ZipZy cloud.
