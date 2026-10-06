"""Connectors: the program each company runs inside its own network.

Lifecycle (status):
    pending  --enroll-->  offline  <--gateway heartbeat-->  online
       \\________________________\\_________________________\\--revoke-->  revoked (final)

This module covers the control-plane side:
- create a connector + a one-time enrollment token (only its SHA-256 hash is stored)
- issue a fresh token while still pending (older unused tokens stop working)
- enroll: token + the connector's public key  ->  connector id   (token is then used up)
- rename, list, revoke

Rules:
- Names are unique inside a company.
- A token works once, only before it expires, only for a pending connector of an active company.
- Revoked is final: the public key is erased so the connector can never authenticate again.
"""

import hashlib
import secrets
import shlex
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Connector, Datasource, EnrollmentToken, Tenant
from app.models.enums import ConnectorStatus, TenantStatus

# "ZipZy connector enrollment token" prefix: lets secret scanners spot leaked tokens.
TOKEN_PREFIX = "zcet_"  # noqa: S105 - a public prefix, not a secret


class ConnectorNotFoundError(Exception):
    pass


class NameTakenError(Exception):
    pass


class NotPendingError(Exception):
    """The action needs a connector that has not enrolled yet."""


class AlreadyRevokedError(Exception):
    pass


class EnrollmentInvalidError(Exception):
    """Unknown, expired, used, or for a connector/company that can no longer enroll."""


@dataclass(slots=True)
class ConnectorInfo:
    connector: Connector
    datasource_count: int
    enrollment_expires_at: datetime | None


@dataclass(slots=True)
class IssuedToken:
    token: str
    expires_at: datetime
    command: str


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def install_command(token: str) -> str:
    """The exact command the customer pastes on their server."""
    s = get_settings()
    q = shlex.quote
    return (
        "docker run -d --name zipzy-connector --restart unless-stopped \\\n"
        f"  -e ZIPZY_ENROLL_TOKEN={q(token)} \\\n"
        f"  -e ZIPZY_URL={q(s.connector_public_url)} \\\n"
        "  -v zipzy-connector-data:/data \\\n"
        "  -v /etc/zipzy/connector.yaml:/config/connector.yaml:ro \\\n"
        f"  {q(s.connector_image)}"
    )


# ---- reading ---------------------------------------------------------------------------------


def _info_query(
    tenant_id: uuid.UUID, now: datetime
) -> Any:  # a select of (Connector, datasource count, token expiry)
    datasources = (
        select(func.count())
        .select_from(Datasource)
        .where(Datasource.connector_id == Connector.id)
        .correlate(Connector)
        .scalar_subquery()
    )
    token_expiry = (
        select(func.max(EnrollmentToken.expires_at))
        .where(
            EnrollmentToken.connector_id == Connector.id,
            EnrollmentToken.used_at.is_(None),
            EnrollmentToken.expires_at > now,
        )
        .correlate(Connector)
        .scalar_subquery()
    )
    return select(Connector, datasources, token_expiry).where(Connector.tenant_id == tenant_id)


async def list_connectors(session: AsyncSession, tenant_id: uuid.UUID) -> list[ConnectorInfo]:
    rows = await session.execute(_info_query(tenant_id, datetime.now(UTC)).order_by(Connector.name))
    return [ConnectorInfo(c, n, exp) for c, n, exp in rows.all()]


async def get_connector(
    session: AsyncSession, tenant_id: uuid.UUID, connector_id: uuid.UUID, *, lock: bool = False
) -> ConnectorInfo:
    query = _info_query(tenant_id, datetime.now(UTC)).where(Connector.id == connector_id)
    if lock:
        query = query.with_for_update(of=Connector)
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise ConnectorNotFoundError
    return ConnectorInfo(row[0], row[1], row[2])


# ---- tokens ----------------------------------------------------------------------------------


async def _issue_token(
    session: AsyncSession, connector: Connector, created_by: uuid.UUID
) -> IssuedToken:
    now = datetime.now(UTC)
    # Only the newest install command may work: retire any older unused ones.
    await session.execute(
        update(EnrollmentToken)
        .where(
            EnrollmentToken.connector_id == connector.id,
            EnrollmentToken.used_at.is_(None),
            EnrollmentToken.expires_at > now,
        )
        .values(expires_at=now)
    )
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=get_settings().enrollment_token_minutes)
    session.add(
        EnrollmentToken(
            connector_id=connector.id,
            token_hash=_hash(raw),
            expires_at=expires_at,
            created_by=created_by,
        )
    )
    await session.flush()
    return IssuedToken(token=raw, expires_at=expires_at, command=install_command(raw))


# ---- writing ---------------------------------------------------------------------------------


async def create_connector(
    session: AsyncSession, *, tenant_id: uuid.UUID, name: str, created_by: uuid.UUID
) -> tuple[Connector, IssuedToken]:
    connector = Connector(
        tenant_id=tenant_id, name=name, status=ConnectorStatus.PENDING, created_by=created_by
    )
    try:
        async with session.begin_nested():
            session.add(connector)
            await session.flush()
    except IntegrityError as exc:
        raise NameTakenError from exc
    await session.refresh(connector)
    return connector, await _issue_token(session, connector, created_by)


async def new_enrollment_token(
    session: AsyncSession, *, tenant_id: uuid.UUID, connector_id: uuid.UUID, created_by: uuid.UUID
) -> tuple[Connector, IssuedToken]:
    info = await get_connector(session, tenant_id, connector_id, lock=True)
    if info.connector.status != ConnectorStatus.PENDING:
        raise NotPendingError
    return info.connector, await _issue_token(session, info.connector, created_by)


async def rename_connector(
    session: AsyncSession, *, tenant_id: uuid.UUID, connector_id: uuid.UUID, name: str
) -> tuple[ConnectorInfo, str | None]:
    """Returns the connector and the old name (None when nothing changed)."""
    info = await get_connector(session, tenant_id, connector_id, lock=True)
    old = info.connector.name
    if name == old:
        return info, None
    try:
        async with session.begin_nested():  # the change must happen INSIDE the savepoint
            info.connector.name = name
            await session.flush()
    except IntegrityError as exc:
        raise NameTakenError from exc
    return info, old


async def revoke_connector(
    session: AsyncSession, *, tenant_id: uuid.UUID, connector_id: uuid.UUID
) -> ConnectorInfo:
    info = await get_connector(session, tenant_id, connector_id, lock=True)
    c = info.connector
    if c.status == ConnectorStatus.REVOKED:
        raise AlreadyRevokedError
    now = datetime.now(UTC)
    c.status = ConnectorStatus.REVOKED
    c.revoked_at = now
    c.public_key = None  # it can never prove who it is again
    await session.execute(
        update(EnrollmentToken)
        .where(EnrollmentToken.connector_id == c.id, EnrollmentToken.used_at.is_(None))
        .values(expires_at=func.least(EnrollmentToken.expires_at, now))
    )
    await session.flush()
    info.enrollment_expires_at = None
    return info


async def enroll(
    session: AsyncSession, *, raw_token: str, public_key: str, version: str | None
) -> Connector:
    """Called by the connector program on first start."""
    now = datetime.now(UTC)
    row = (
        await session.execute(
            select(EnrollmentToken, Connector)
            .join(Connector, Connector.id == EnrollmentToken.connector_id)
            .join(Tenant, Tenant.id == Connector.tenant_id)
            .where(
                EnrollmentToken.token_hash == _hash(raw_token),
                EnrollmentToken.used_at.is_(None),
                EnrollmentToken.expires_at > now,
                Connector.status == ConnectorStatus.PENDING,
                Tenant.status == TenantStatus.ACTIVE,
            )
            .with_for_update(of=(EnrollmentToken, Connector))
        )
    ).one_or_none()
    if row is None:
        raise EnrollmentInvalidError
    token, connector = row
    token.used_at = now
    connector.public_key = public_key
    connector.version = version
    connector.status = ConnectorStatus.OFFLINE  # enrolled; the gateway marks it online
    await session.flush()
    return connector
