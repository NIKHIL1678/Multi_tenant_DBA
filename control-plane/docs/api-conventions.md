# Control Plane API conventions

The rules every endpoint follows. The dashboard (and anyone else calling the API) can rely on
them. `tests/test_api_conventions.py` fails if an error code or audit action used in the code
is missing from this page.

Interactive reference with every endpoint and field: `http://localhost:8000/docs` (development).

## Basics

| Topic | Rule |
|---|---|
| Base path | Everything is under `/v1/...` (health checks: `/healthz`, `/readyz`) |
| Format | JSON in, JSON out. UTF-8 |
| IDs | UUID strings, e.g. `"6b96a494-5e3b-5855-82b7-d97b4432ecf6"`. Audit rows use integers |
| Time | ISO 8601 in UTC, e.g. `"2026-10-06T05:30:12.123456Z"` |
| Names | `snake_case` fields everywhere |
| Company scope | Company resources live under `/v1/tenants/{tenant_id}/...` |

## Signing in

| Way | How |
|---|---|
| Normal | `POST /v1/auth/login` → `{"access_token", "expires_in"}`. Send `Authorization: Bearer <access_token>` on every call. The access token lives 15 minutes |
| Staying signed in | The refresh token is an httpOnly cookie (`zdba_refresh`, path `/v1/auth`). Call `POST /v1/auth/refresh` (with credentials) to get a new access token. Never store tokens in localStorage |
| Signing out | `POST /v1/auth/logout` |
| Development only | `X-Dev-User: <email>` header, when `DEV_AUTH=true` in development/test |

## Permissions: 404 vs 403

- **404 `not_found`**: you are not an active member of that company, **or** the thing is in an
  environment you may not see. Outsiders cannot even learn that something exists.
- **403 `forbidden`**: you can see it, but your role does not allow this action.
- Permissions can differ **per environment** (role overrides). Lists only contain what you may see.

Every company response that matters for the UI tells you what you may do:
`GET /v1/tenants/{id}` → `my_role_key` and `my_permissions`. Use them to hide buttons; the API
still checks every request.

## Errors

Every error has the same shape:

```json
{
  "error": {
    "code": "conflict",
    "message": "A connector with this name already exists.",
    "request_id": "6e616d62627249ab954c0827b4f6c525",
    "details": [{"field": "name", "message": "..."}]
  }
}
```

- `code`: stable, machine-readable. **Switch on this**, never on `message`.
- `message`: for humans; may change wording.
- `request_id`: also in the `X-Request-ID` response header. Show it in error toasts; support
  finds the exact request in the logs (and in the audit log) with it.
- `details`: only for `validation_error`: one entry per invalid field.

### Error codes

| HTTP | `code` | Meaning |
|---|---|---|
| 400 | `bad_request` | The request could not be understood |
| 401 | `unauthenticated` | Not signed in, token expired or invalid. Refresh, else go to sign-in |
| 401 | `enrollment_invalid` | Connector install command is invalid, expired or already used |
| 403 | `forbidden` | Signed in, but not allowed to do this |
| 404 | `not_found` | Does not exist, or you may not see it |
| 404 | `invitation_invalid` | Invitation link is invalid, expired or already used |
| 405 | `method_not_allowed` | Wrong HTTP method for this URL |
| 409 | `conflict` | Clashes with current state: name taken, last Owner, already revoked, … |
| 422 | `validation_error` | Some fields are invalid; see `details` |
| 422 | `invalid_role` | That role does not exist in this company |
| 422 | `invalid_cursor` | The page cursor is broken; start the list again |
| 429 | `rate_limited` | Too many requests; wait and retry |
| 500 | `internal_error` | Our bug. Show the `request_id` |
| any | `error` | Fallback for any other HTTP status |

## Lists and pagination

Lists that can grow large are **paginated with a cursor**:

```
GET /v1/tenants/{id}/datasources?limit=50
→ {"items": [...], "next_cursor": "WyJwcm9kdWN0aW9uIiwi..."}

GET /v1/tenants/{id}/datasources?limit=50&cursor=WyJwcm9kdWN0aW9uIiwi...
→ {"items": [...], "next_cursor": null}        ← null = last page
```

- `limit`: 1–200, default 50.
- `cursor`: copy `next_cursor` exactly; never build or edit it. A cursor only works for the list
  (and filters) it came from.
- New rows never cause duplicates or skipped rows while someone is paging.

| Paginated list | Sort order |
|---|---|
| `GET /v1/tenants/{id}/members` | active first, then email (case-insensitive) |
| `GET /v1/tenants/{id}/environments` | production first, then name |
| `GET /v1/tenants/{id}/datasources` | environment name, then database name |
| `GET /v1/tenants/{id}/audit-log` | newest first |

Small lists with a natural limit are **plain arrays** (no `items` wrapper): my companies
(`GET /v1/tenants`), roles, connectors, pending invitations.

## Changes are audited

Every change writes an audit row in the same transaction (if the change fails, no row).
Read them with `GET /v1/tenants/{id}/audit-log` (needs `audit.read`). Filter with
`action=member.` (prefix, ends with a dot) or an exact action.

| Action | When |
|---|---|
| `tenant.created` | A company was created |
| `tenant.renamed` | A company was renamed |
| `member.role_changed` | A member's company-wide role changed |
| `member.suspended` | A member was suspended |
| `member.reactivated` | A suspended member was reactivated |
| `member.environment_role_set` | A per-environment role was set or changed |
| `member.environment_role_removed` | A per-environment role was removed |
| `invitation.created` | Someone was invited (replaces older pending invites to the same email) |
| `invitation.revoked` | A pending invitation was cancelled |
| `invitation.accepted` | An invited person joined |
| `environment.created` | An environment was created |
| `environment.updated` | An environment was renamed or its production flag changed |
| `environment.deleted` | An empty environment was deleted |
| `connector.created` | A connector was created (the install token is never logged) |
| `connector.token_issued` | A new install command was issued |
| `connector.enrolled` | A connector installed itself (actor: the connector) |
| `connector.renamed` | A connector was renamed |
| `connector.revoked` | A connector was revoked (final) |
| `datasource.discovered` | A connector reported a new database (actor: the connector) |
| `datasource.moved` | A database moved to another environment |
| `datasource.deleted` | A database was removed from ZipZy |

Never in the audit log: passwords, tokens, database credentials, customer row data.