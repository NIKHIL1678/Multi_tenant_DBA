"""Companies (tenants).

POST   /v1/tenants                       create a company (caller becomes Owner)
GET    /v1/tenants                       companies I belong to
GET    /v1/tenants/{tenant_id}           one company            needs metadata.read
PATCH  /v1/tenants/{tenant_id}           rename                 needs org.manage
GET    /v1/tenants/{tenant_id}/overview  dashboard counts       needs metadata.read
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from app.api.errors import conflict
from app.audit import record_audit
from app.auth.current_user import CurrentUser, DbSession
from app.auth.permissions import require
from app.core.logging import tenant_id_var
from app.models import Tenant
from app.rbac.catalog import SYSTEM_ROLE_PERMISSIONS, Permission, SystemRole
from app.rbac.service import AccessContext
from app.schemas.tenants import TenantCreateIn, TenantOut, TenantOverviewOut, TenantUpdateIn
from app.services import tenants as svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/tenants", tags=["tenants"])

CanRead = Annotated[AccessContext, Depends(require(Permission.METADATA_READ))]
CanManageOrg = Annotated[AccessContext, Depends(require(Permission.ORG_MANAGE))]


def _out(tenant: Tenant, role_key: str, permissions: frozenset[str]) -> TenantOut:
    return TenantOut(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        plan=tenant.plan,
        status=tenant.status,
        created_at=tenant.created_at,
        my_role_key=role_key,
        my_permissions=sorted(permissions),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreateIn, user: CurrentUser, session: DbSession, request: Request
) -> TenantOut:
    try:
        tenant = await svc.create_tenant(
            session, owner_id=user.user_id, name=body.name, slug=body.slug
        )
    except svc.SlugTakenError:
        raise conflict("This company URL name is already taken.") from None

    tenant_id_var.set(str(tenant.id))
    await record_audit(
        session,
        tenant_id=tenant.id,
        actor_id=user.user_id,
        action="tenant.created",
        target_type="tenant",
        target_id=tenant.id,
        details={"name": tenant.name, "slug": tenant.slug},
        request=request,
    )
    await session.commit()
    await session.refresh(tenant)
    logger.info("tenant created", extra={"slug": tenant.slug})
    owner_perms = frozenset(str(p) for p in SYSTEM_ROLE_PERMISSIONS[SystemRole.OWNER])
    return _out(tenant, SystemRole.OWNER.value, owner_perms)


@router.get("")
async def list_tenants(user: CurrentUser, session: DbSession) -> list[TenantOut]:
    return [
        _out(item.tenant, item.role_key, item.permissions)
        for item in await svc.list_my_tenants(session, user.user_id)
    ]


@router.get("/{tenant_id}")
async def get_tenant(tenant_id: uuid.UUID, access: CanRead, session: DbSession) -> TenantOut:
    tenant = await svc.get_tenant(session, tenant_id)
    return _out(tenant, access.role_key, access.permissions)


@router.patch("/{tenant_id}")
async def update_tenant(
    tenant_id: uuid.UUID,
    body: TenantUpdateIn,
    access: CanManageOrg,
    user: CurrentUser,
    session: DbSession,
    request: Request,
) -> TenantOut:
    tenant = await svc.get_tenant(session, tenant_id)
    old_name = tenant.name
    if body.name != old_name:
        tenant.name = body.name
        await record_audit(
            session,
            tenant_id=tenant_id,
            actor_id=user.user_id,
            action="tenant.renamed",
            target_type="tenant",
            target_id=tenant_id,
            details={"from": old_name, "to": body.name},
            request=request,
        )
        await session.commit()
        await session.refresh(tenant)
    return _out(tenant, access.role_key, access.permissions)


@router.get("/{tenant_id}/overview")
async def tenant_overview(
    tenant_id: uuid.UUID, _: CanRead, session: DbSession
) -> TenantOverviewOut:
    envs, members, connectors, datasources = await svc.overview_counts(session, tenant_id)
    return TenantOverviewOut(
        tenant_id=tenant_id,
        environments=envs,
        members=members,
        connectors_by_status=connectors,
        datasources_by_engine=datasources,
    )
