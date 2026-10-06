"""The permission guard: one line on every tenant endpoint.

    @router.patch("/v1/tenants/{tenant_id}")
    async def update(access: Annotated[AccessContext, Depends(require(Permission.ORG_MANAGE))]):

Rules (the "block wall" between companies):
- Not a member of the tenant (or tenant/user/membership not active) -> 404.
  We answer "not found", never "forbidden", so outsiders cannot even learn a tenant exists.
- Member, but the role lacks the permission -> 403.

Use `require_member` (membership only) when the endpoint decides per environment, e.g.
datasources: a Backend Developer may be a Viewer in production but a Developer in staging.
"""

import uuid
from collections.abc import Awaitable, Callable

from app.api.errors import forbidden, not_found
from app.auth.current_user import CurrentUser, DbSession
from app.core.logging import tenant_id_var
from app.rbac.catalog import Permission
from app.rbac.service import AccessContext, resolve_access

AccessDependency = Callable[..., Awaitable[AccessContext]]


async def _membership(tenant_id: uuid.UUID, user: CurrentUser, session: DbSession) -> AccessContext:
    access = await resolve_access(session, user_id=user.user_id, tenant_id=tenant_id)
    if access is None:
        raise not_found("Company")
    tenant_id_var.set(str(tenant_id))
    return access


def require(permission: Permission) -> AccessDependency:
    async def dependency(
        tenant_id: uuid.UUID, user: CurrentUser, session: DbSession
    ) -> AccessContext:
        access = await _membership(tenant_id, user, session)
        if not access.has(permission):
            raise forbidden()
        return access

    dependency.__name__ = f"require_{permission.value.replace('.', '_')}"
    return dependency


async def require_member(
    tenant_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> AccessContext:
    """Any active member. For endpoints that check permissions per environment themselves."""
    return await _membership(tenant_id, user, session)
