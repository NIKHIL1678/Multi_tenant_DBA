"""Datasources: the customer's databases, as reported by their connectors.

Where they come from:
    The connector reads connector.yaml, checks each database and reports
    name + engine + version + capabilities (never passwords, never data).
    `sync_from_connector` turns that report into rows. The gateway (Phase 4) calls it.

Where they go (environment):
    1. the `environment:` hint in connector.yaml, if that environment exists, else
    2. the company's production environment: the STRICTEST place is the safe default.
       A production database must never land somewhere with weaker rules by accident.
    Users can then move it from the dashboard.

Rules:
- Users see only datasources in environments where they have `metadata.read`.
- Changing one needs `datasources.manage` in its environment (and in the target one, when moving).
- Taking a database OUT of production (move or delete) also needs `org.manage` (Owner).
- A database the connector stops reporting is not deleted, only marked `unknown`.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.models import Connector, Datasource, Environment
from app.models.enums import ActorType, ConnectorStatus, DatasourceStatus
from app.rbac.catalog import Permission
from app.rbac.service import AccessContext, resolve_access
from app.schemas.datasources import ReportedDatasource


class DatasourceNotFoundError(Exception):
    pass


class EnvironmentNotFoundError(Exception):
    pass


class NotAllowedError(Exception):
    pass


class NeedsOrgManageError(Exception):
    pass


class ConnectorRevokedError(Exception):
    pass


@dataclass(slots=True)
class DatasourceInfo:
    datasource: Datasource
    connector: Connector
    environment: Environment


@dataclass(slots=True)
class SyncResult:
    created: list[Datasource] = field(default_factory=list)
    updated: list[Datasource] = field(default_factory=list)
    missing: list[Datasource] = field(default_factory=list)


# ---- reading ---------------------------------------------------------------------------------


def _base_query(tenant_id: uuid.UUID) -> Any:  # select of (Datasource, Connector, Environment)
    return (
        select(Datasource, Connector, Environment)
        .join(Connector, Connector.id == Datasource.connector_id)
        .join(Environment, Environment.id == Datasource.environment_id)
        .where(Datasource.tenant_id == tenant_id)
    )


async def list_datasources(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    visible_environments: Iterable[uuid.UUID],
    environment_id: uuid.UUID | None = None,
    connector_id: uuid.UUID | None = None,
    engine: str | None = None,
    status: str | None = None,
) -> list[DatasourceInfo]:
    visible = set(visible_environments)
    if not visible:
        return []
    query = _base_query(tenant_id).where(Datasource.environment_id.in_(visible))
    if environment_id is not None:
        query = query.where(Datasource.environment_id == environment_id)
    if connector_id is not None:
        query = query.where(Datasource.connector_id == connector_id)
    if engine is not None:
        query = query.where(Datasource.engine == engine)
    if status is not None:
        query = query.where(Datasource.status == status)
    rows = await session.execute(query.order_by(Environment.name, Datasource.local_name))
    return [DatasourceInfo(d, c, e) for d, c, e in rows.all()]


async def get_datasource(
    session: AsyncSession, tenant_id: uuid.UUID, datasource_id: uuid.UUID, *, lock: bool = False
) -> DatasourceInfo:
    query = _base_query(tenant_id).where(Datasource.id == datasource_id)
    if lock:
        query = query.with_for_update(of=Datasource)
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise DatasourceNotFoundError
    return DatasourceInfo(row[0], row[1], row[2])


async def access_in(
    session: AsyncSession, *, user_id: uuid.UUID, tenant_id: uuid.UUID, environment_id: uuid.UUID
) -> AccessContext | None:
    return await resolve_access(
        session, user_id=user_id, tenant_id=tenant_id, environment_id=environment_id
    )


async def get_visible(
    session: AsyncSession, *, user_id: uuid.UUID, tenant_id: uuid.UUID, datasource_id: uuid.UUID
) -> DatasourceInfo:
    """One datasource, or 'not found' when it is in an environment the user cannot see."""
    info = await get_datasource(session, tenant_id, datasource_id)
    access = await access_in(
        session, user_id=user_id, tenant_id=tenant_id, environment_id=info.environment.id
    )
    if access is None or not access.has(Permission.METADATA_READ):
        raise DatasourceNotFoundError
    return info


# ---- changing --------------------------------------------------------------------------------


async def _require_manage(
    session: AsyncSession, *, user_id: uuid.UUID, tenant_id: uuid.UUID, env: Environment
) -> AccessContext:
    access = await access_in(session, user_id=user_id, tenant_id=tenant_id, environment_id=env.id)
    if access is None or not access.has(Permission.METADATA_READ):
        raise DatasourceNotFoundError  # cannot even see it
    if not access.has(Permission.DATASOURCES_MANAGE):
        raise NotAllowedError
    return access


async def move_datasource(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    datasource_id: uuid.UUID,
    environment_id: uuid.UUID,
) -> tuple[DatasourceInfo, Environment | None]:
    """Returns the datasource and the environment it came from (None if nothing changed)."""
    info = await get_datasource(session, tenant_id, datasource_id, lock=True)
    source_access = await _require_manage(
        session, user_id=user_id, tenant_id=tenant_id, env=info.environment
    )
    if environment_id == info.environment.id:
        return info, None

    target = await session.scalar(
        select(Environment).where(
            Environment.id == environment_id, Environment.tenant_id == tenant_id
        )
    )
    if target is None:
        raise EnvironmentNotFoundError
    target_access = await access_in(
        session, user_id=user_id, tenant_id=tenant_id, environment_id=target.id
    )
    if target_access is None or not target_access.has(Permission.DATASOURCES_MANAGE):
        raise NotAllowedError
    if (
        info.environment.is_production
        and not target.is_production
        and not source_access.has(Permission.ORG_MANAGE)
    ):
        raise NeedsOrgManageError

    source = info.environment
    info.datasource.environment_id = target.id
    await session.flush()
    info.environment = target
    return info, source


async def delete_datasource(
    session: AsyncSession, *, user_id: uuid.UUID, tenant_id: uuid.UUID, datasource_id: uuid.UUID
) -> DatasourceInfo:
    """Removes it from ZipZy only. If it is still in connector.yaml it will be reported again."""
    info = await get_datasource(session, tenant_id, datasource_id, lock=True)
    access = await _require_manage(
        session, user_id=user_id, tenant_id=tenant_id, env=info.environment
    )
    if info.environment.is_production and not access.has(Permission.ORG_MANAGE):
        raise NeedsOrgManageError
    await session.delete(info.datasource)
    await session.flush()
    return info


# ---- reported by a connector -----------------------------------------------------------------


async def _default_environment(
    session: AsyncSession, tenant_id: uuid.UUID, hint: str | None
) -> Environment | None:
    envs = (
        await session.scalars(
            select(Environment)
            .where(Environment.tenant_id == tenant_id)
            .order_by(Environment.is_production.desc(), Environment.name)
        )
    ).all()
    if hint is not None:
        wanted = hint.strip().lower()
        for env in envs:
            if env.name == wanted:
                return env
    return envs[0] if envs else None  # production first: the strictest place


async def sync_from_connector(
    session: AsyncSession, *, connector_id: uuid.UUID, reported: list[ReportedDatasource]
) -> SyncResult:
    """Make our rows match what the connector just reported."""
    connector = await session.get(Connector, connector_id, with_for_update=True)
    if connector is None or connector.status == ConnectorStatus.REVOKED:
        raise ConnectorRevokedError

    now = datetime.now(UTC)
    existing = {
        d.local_name: d
        for d in (
            await session.scalars(select(Datasource).where(Datasource.connector_id == connector_id))
        ).all()
    }
    result = SyncResult()
    seen: set[str] = set()

    for report in reported:
        if report.local_name in seen:
            continue  # duplicate names in one report: first one wins
        seen.add(report.local_name)
        status = DatasourceStatus.CONNECTED if report.reachable else DatasourceStatus.ERROR
        ds = existing.get(report.local_name)
        if ds is None:
            env = await _default_environment(session, connector.tenant_id, report.environment)
            if env is None:
                continue  # a company always has environments; nothing safe to do otherwise
            ds = Datasource(
                tenant_id=connector.tenant_id,
                connector_id=connector.id,
                environment_id=env.id,
                local_name=report.local_name,
                engine=report.engine,
            )
            session.add(ds)
            result.created.append(ds)
        else:
            result.updated.append(ds)
        ds.engine = report.engine
        ds.version = report.version
        ds.capabilities = report.capabilities
        ds.status = status
        ds.last_checked_at = now

    for name, ds in existing.items():
        if name not in seen and ds.status != DatasourceStatus.UNKNOWN:
            ds.status = DatasourceStatus.UNKNOWN
            result.missing.append(ds)

    await session.flush()
    for ds in result.created:
        await record_audit(
            session,
            tenant_id=connector.tenant_id,
            actor_type=ActorType.CONNECTOR,
            actor_id=connector.id,
            action="datasource.discovered",
            target_type="datasource",
            target_id=ds.id,
            details={"name": ds.local_name, "engine": ds.engine},
        )
    return result
