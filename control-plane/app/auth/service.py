"""Sign-up, sign-in and session (refresh token) lifecycle."""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import (
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    password_needs_rehash,
    verify_password,
)
from app.core.config import get_settings
from app.models import AuthSession, User
from app.models.enums import AuthProvider, UserStatus

logger = logging.getLogger(__name__)


class EmailTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidRefreshError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ClientInfo:
    user_agent: str | None
    ip_address: str | None


async def sign_up(session: AsyncSession, *, email: str, password: str, full_name: str) -> User:
    if await session.scalar(select(User.id).where(User.email == email)) is not None:
        raise EmailTakenError
    user = User(
        email=email,
        full_name=full_name,
        auth_provider=AuthProvider.PASSWORD,
        password_hash=hash_password(password),
    )
    try:
        async with session.begin_nested():  # a concurrent sign-up can still win the race
            session.add(user)
            await session.flush()
    except IntegrityError as exc:
        raise EmailTakenError from exc
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    """Same error (and similar timing) whether the email is unknown or the password is wrong."""
    user = await session.scalar(select(User).where(User.email == email))
    if not verify_password(password, user.password_hash if user else None) or user is None:
        raise InvalidCredentialsError
    if user.status != UserStatus.ACTIVE:
        raise InvalidCredentialsError
    if user.password_hash and password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


async def _create_session(
    session: AsyncSession, user: User, client: ClientInfo
) -> tuple[str, AuthSession]:
    raw, token_hash = new_refresh_token()
    row = AuthSession(
        user_id=user.id,
        refresh_token_hash=token_hash,
        expires_at=datetime.now(UTC) + timedelta(days=get_settings().refresh_token_days),
        user_agent=(client.user_agent or "")[:300] or None,
        ip_address=client.ip_address,
    )
    session.add(row)
    await session.flush()
    return raw, row


async def start_session(session: AsyncSession, user: User, client: ClientInfo) -> str:
    """Create a signed-in session; return the raw refresh token (only ever sent to the client)."""
    raw, _ = await _create_session(session, user, client)
    return raw


async def rotate_session(session: AsyncSession, raw: str, client: ClientInfo) -> tuple[User, str]:
    """Exchange a refresh token for a new one.

    A token that was already rotated or revoked being used again means it was copied:
    every session of that user is revoked (they must sign in again everywhere).
    """
    now = datetime.now(UTC)
    current = await session.scalar(
        select(AuthSession).where(AuthSession.refresh_token_hash == hash_refresh_token(raw))
    )
    if current is None:
        raise InvalidRefreshError
    if current.revoked_at is not None:
        if current.replaced_by is not None:
            logger.warning("refresh token reuse detected", extra={"user_id": str(current.user_id)})
            await revoke_all_sessions(session, current.user_id)
        raise InvalidRefreshError
    if current.expires_at <= now:
        raise InvalidRefreshError

    user = await session.get(User, current.user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise InvalidRefreshError

    new_raw, replacement = await _create_session(session, user, client)
    current.revoked_at = now
    current.replaced_by = replacement.id
    current.last_used_at = now
    return user, new_raw


async def end_session(session: AsyncSession, raw: str) -> None:
    await session.execute(
        update(AuthSession)
        .where(
            AuthSession.refresh_token_hash == hash_refresh_token(raw),
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_all_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
