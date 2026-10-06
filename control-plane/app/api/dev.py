"""Development-only helpers. This router is not mounted unless DEV_AUTH=true."""

from fastapi import APIRouter
from sqlalchemy import select

from app.auth.current_user import DbSession
from app.models import User
from app.models.enums import UserStatus
from app.schemas.me import DevUserOut

router = APIRouter(prefix="/v1/dev", tags=["dev"])


@router.get("/users")
async def list_dev_users(session: DbSession) -> list[DevUserOut]:
    """Users the dashboard's dev sign-in picker can choose from."""
    users = (
        await session.scalars(
            select(User).where(User.status == UserStatus.ACTIVE).order_by(User.email).limit(200)
        )
    ).all()
    return [DevUserOut(email=u.email, full_name=u.full_name) for u in users]
