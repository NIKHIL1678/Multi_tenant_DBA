"""The signed-in user and the companies they belong to."""

from fastapi import APIRouter
from sqlalchemy import select

from app.auth.current_user import CurrentUser, DbSession
from app.models import Role, Tenant, TenantMember
from app.models.enums import MemberStatus, TenantStatus
from app.schemas.me import MembershipOut, MeOut

router = APIRouter(prefix="/v1", tags=["me"])


@router.get("/me")
async def get_me(user: CurrentUser, session: DbSession) -> MeOut:
    rows = (
        await session.execute(
            select(Tenant.id, Tenant.name, Tenant.slug, Role.key, Role.name)
            .join(TenantMember, TenantMember.tenant_id == Tenant.id)
            .join(Role, Role.id == TenantMember.role_id)
            .where(
                TenantMember.user_id == user.user_id,
                TenantMember.status == MemberStatus.ACTIVE,
                Tenant.status == TenantStatus.ACTIVE,
            )
            .order_by(Tenant.name)
        )
    ).all()
    return MeOut(
        id=user.user_id,
        email=user.email,
        full_name=user.full_name,
        memberships=[
            MembershipOut(
                tenant_id=r[0], tenant_name=r[1], tenant_slug=r[2], role_key=r[3], role_name=r[4]
            )
            for r in rows
        ],
    )