# 05 — Access Control (RBAC)

## Concepts

- **Tenant** — a customer company.
- **Member** — a user inside a tenant. One user can be a member of many tenants.
- **Permission** — one specific ability, e.g. `data.read`.
- **Role** — a named bundle of permissions. A member has one tenant-wide role.
- **Environment override** — optionally, a different role for one environment
(e.g. Backend Developer everywhere, but Viewer in production).

Adding a role or changing a mapping is a data change (a migration), not a code change.

## Permissions

Permission
Meaning

`org.manage`
Manage tenant settings, billing and deletion

`members.manage`
Invite and remove members, change roles

`connectors.manage`
Create and revoke connectors, issue enrollment tokens

`datasources.manage`
Add and remove datasources, assign environments

`metadata.read`
View health, schema, indexes and statistics (no row data)

`data.read`
Run read queries that return row data

`findings.read`
View agent findings and recommendations

`actions.request`
Propose a change to a datasource

`actions.approve`
Approve a proposed change

`actions.execute`
Execute an approved change

`audit.read`
View the audit log

`metadata.read` and `data.read` are separate on purpose: people can operate a database
without seeing customer data (important for privacy law such as India's DPDP Act).

## System roles

Permission
Owner
DBA
IT Admin
Backend Dev
Viewer

org.manage
✅

members.manage
✅

✅

connectors.manage
✅
✅
✅

datasources.manage
✅
✅
✅

metadata.read
✅
✅
✅
✅
✅

data.read
✅
✅

✅

findings.read
✅
✅
✅
✅
✅

actions.request
✅
✅

✅

actions.approve
✅
✅

actions.execute
✅
✅

audit.read
✅
✅
✅

Keys: `owner`, `dba`, `it_admin`, `backend_dev`, `viewer`.

## Resolution rules

Given a user, a tenant and optionally an environment (or a datasource, which implies both):

1. The **user**, the **tenant** and the **membership** must all be active. Otherwise: no access.
2. If an environment is given and the member has an override for it, use that role.
Otherwise use the member's tenant-wide role.
3. The effective role must be a **system role** or a role **of the same tenant**. A role
belonging to another tenant grants nothing, even if a bad row points at it.
4. Effective permissions = the permissions mapped to that role.
5. Every allow **and** deny on a data-plane request is written to `audit_log`.

## Custom roles

Tenants may define their own roles (`roles.tenant_id` set). Role keys are unique within a
tenant; the same key may exist in different tenants. Custom roles are supported by the
schema from day one; the API for them is a later phase.

## Separation of duties (actions)

A change goes through: `actions.request` → `actions.approve` → `actions.execute`.
For production environments, the approver must be a different person from the requester.

## Source of truth

- Runtime catalog: `control-plane/app/rbac/catalog.py`.
- Database seed: an Alembic migration with the same data frozen inside it.
- A test fails if the two differ, so any change to the catalog must ship with a new migration.

## Examples

Who
Where
Can
Cannot

Rahul, Backend Dev (override: Viewer in production)
staging DB
read rows, propose index
approve

Rahul
production DB
see health and schema
read rows

Priya, IT Admin
any DB
add connector, invite people
read rows, approve changes

Freelance DBA, member of 3 tenants
each tenant
whatever that tenant's role allows
anything in a tenant they are not a member of

