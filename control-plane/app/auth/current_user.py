"""Who is calling? One dependency every protected endpoint uses.

Endpoints depend on `CurrentUser` and never read headers or tokens themselves.

    Authorization: Bearer <access token>   normal sign-in (always on)
    X-Dev-User: <email>                    local development only (DEV_AUTH=true)
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import unauthenticated
from app.auth.security import InvalidTokenError, decode_access_token
from app.core.config import get_settings
from app.core.db import get_session
from app.core.logging import user_id_var
from app.models import User
from app.models.enums import UserStatus

DEV_USER_HEADER = "X-Dev-User"


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    email: str
    full_name: str | None


def _active(user: User | None) -> Principal:
    if user is None or user.status != UserStatus.ACTIVE:
        raise unauthenticated("Unknown or disabled user.")
    return Principal(user_id=user.id, email=user.email, full_name=user.full_name)


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    x_dev_user: Annotated[str | None, Header(alias=DEV_USER_HEADER)] = None,
) -> Principal:
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise unauthenticated("Use 'Authorization: Bearer <token>'.")
        try:
            user_id = decode_access_token(token.strip())
        except InvalidTokenError:
            raise unauthenticated("Your session has expired or is invalid.") from None
        principal = _active(await session.get(User, user_id))
    elif x_dev_user and get_settings().dev_auth:
        principal = _active(await session.scalar(select(User).where(User.email == x_dev_user)))
    else:
        raise unauthenticated()
    user_id_var.set(str(principal.user_id))
    return principal


CurrentUser = Annotated[Principal, Depends(get_current_user)]
DbSession = Annotated[AsyncSession, Depends(get_session)]