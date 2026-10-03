# 03 — DBA Capabilities

Everything a DBA does in an organisation, grouped into domains, and which agent owns it.
**Tier:** R = read-only (safe), W = changes the database (requires approval).

#
Domain
Typical tasks
Tier
Agent
Phase

1
Installation & configuration
Install/upgrade engines, size instances, tune config (buffer pool, `shared_buffers`, `max_connections`, WiredTiger cache), charset/timezone, env parity
W
Provisioning
Later

2
Monitoring & health
Uptime, CPU/memory/disk/IOPS, connections, locks and deadlocks, replication lag, cache hit ratio, error log, alerting, health reports
R
Health & Monitoring
4

3
Performance tuning
Slow query analysis, execution plans, missing/unused/duplicate indexes, query rewrites, statistics refresh, vacuum/fragmentation, connection pooling, N+1 detection
R (+W for fixes)
Query Performance
5

4
Schema & data model
Schema review, DDL review, online migration planning, constraints, partitioning, MongoDB document design, schema drift
R (+W)
Schema & Migration
7+

5
Backup & recovery
Strategy, schedule monitoring, backup verification, point-in-time recovery readiness, restore drills, RTO/RPO, retention and encryption
R (+W for drills)
Backup & Recovery
7+

6
High availability & DR
Replication setup/health, clusters, failover planning and tests, DR replicas, split-brain detection
R (+W)
Backup & Recovery
7+

7
Security & access
Users and roles, least privilege, grant audits, stale accounts, auth policy, TLS and encryption, network exposure, audit logging, secret rotation
R (+W)
Security & Compliance
7+

8
Compliance & governance
Data classification (PII), retention/purge (DPDP Act, GDPR), audit evidence (SOC 2, ISO 27001), erasure requests, data dictionary
R
Security & Compliance
7+

9
Capacity & cost
Storage growth forecast, throughput trends, right-sizing, reserved capacity, cold-data archiving
R
Capacity & Cost
7+

10
Data operations
Import/export, cross-engine migration, prod→staging refresh with masking, data quality checks, archival/purge jobs, CDC pipelines
W
Ops Executor
Later

11
Maintenance
Index rebuilds, space reclaim, log rotation (binlog/WAL), maintenance windows, scheduled jobs, certificate rotation
W
Ops Executor
Later

12
Incident management
Outage diagnosis, kill runaway/blocking queries, disk-full emergencies, replication breaks, corruption, post-mortems
R detect / W remediate
Health (detect) + Ops Executor (fix)
4 / 6

13
Developer support
Query and PR review, schema consultation, just-in-time access, "why is my query slow?"
R
Query Performance
5

14
Upgrades & migrations
Major version upgrades, compatibility checks, engine changes, zero-downtime cutovers
W
Schema & Migration
Later

## Agent roster

Agent
Domains
Writes?

Orchestrator
Routes requests and alerts to specialists, merges results
No

Health & Monitoring
2, 12 (detection)
No

Query Performance
3, 13
Proposes only

Schema & Migration
4, 14
Proposes only

Backup & Recovery
5, 6
Proposes only

Security & Compliance
7, 8
Proposes only

Capacity & Cost
9
No

Ops Executor
10, 11, 12 (remediation)
Executes **approved** actions only

Provisioning
1
Later

## Autonomy levels

1. **Observe** — collect metrics and metadata.
2. **Recommend** — produce findings with plain-language impact and a proposed fix.
3. **Execute with approval** — a member with `actions.approve` approves; one with
`actions.execute` runs it.
4. **Autonomous** — only for an explicit allow-list of safe operations, per tenant, opt-in.
Not in the initial phases.
