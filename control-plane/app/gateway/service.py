"""Database side of the gateway: who may connect, and online/offline bookkeeping."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Connector, Tenant
from app.models.enums import ConnectorStatus, TenantStatus
from app.schemas.datasources import ReportedDatasource
from app.services.datasources import sync_from_connector

# Write last_seen_at at most this often: a pong every 20 s must not mean a write every 20 s.
LAST_SEEN_EVERY = timedelta(seconds=60)


class ConnectorRejectedError(Exception):
    """Unknown, revoked or never-enrolled connector, or its company is not active."""


async def load_for_handshake(session: AsyncSession, connector_id: uuid.UUID) -> Connector:
    row = (
        await session.execute(
            select(Connector, Tenant.status)
            .join(Tenant, Tenant.id == Connector.tenant_id)
            .where(Connector.id == connector_id)
        )
    ).one_or_none()
    if row is None:
        raise ConnectorRejectedError
    connector, tenant_status = row
    if (
        connector.status in (ConnectorStatus.REVOKED, ConnectorStatus.PENDING)
        or connector.public_key is None
        or tenant_status != TenantStatus.ACTIVE
    ):
        raise ConnectorRejectedError
    return connector


async def mark_online(
    session: AsyncSession,
    connector_id: uuid.UUID,
    *,
    version: str | None,
    databases: list[ReportedDatasource],
) -> None:
    """After a good handshake: online, remember the version, and sync the reported databases."""
    connector = await session.get(Connector, connector_id, with_for_update=True)
    if connector is None or connector.status == ConnectorStatus.REVOKED:
        raise ConnectorRejectedError
    connector.status = ConnectorStatus.ONLINE
    connector.last_seen_at = datetime.now(UTC)
    if version:
        connector.version = version
    await sync_from_connector(session, connector_id=connector_id, reported=databases)
    await session.commit()


async def apply_report(
    session: AsyncSession, connector_id: uuid.UUID, databases: list[ReportedDatasource]
) -> None:
    await sync_from_connector(session, connector_id=connector_id, reported=databases)
    await session.execute(
        update(Connector).where(Connector.id == connector_id).values(last_seen_at=datetime.now(UTC))
    )
    await session.commit()


async def touch(session: AsyncSession, connector_id: uuid.UUID) -> None:
    await session.execute(
        update(Connector)
        .where(Connector.id == connector_id, Connector.status == ConnectorStatus.ONLINE)
        .values(last_seen_at=datetime.now(UTC))
    )
    await session.commit()


async def mark_offline(session: AsyncSession, connector_id: uuid.UUID) -> None:
    """Link closed. A revoked connector stays revoked."""
    await session.execute(
        update(Connector)
        .where(Connector.id == connector_id, Connector.status == ConnectorStatus.ONLINE)
        .values(status=ConnectorStatus.OFFLINE, last_seen_at=datetime.now(UTC))
    )
    await session.commit()


async def reset_online_flags(session: AsyncSession) -> int:
    """At startup no link exists yet, so nobody is online. Returns how many were reset."""
    result = await session.execute(
        update(Connector)
        .where(Connector.status == ConnectorStatus.ONLINE)
        .values(status=ConnectorStatus.OFFLINE)
    )
    await session.commit()
    return int(result.rowcount or 0)  # type: ignore[attr-defined]
