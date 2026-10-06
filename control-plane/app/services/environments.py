"""Environments: groups of databases inside a company (production, staging, ...).

Rules:
- Names are unique inside a company (lowercase, e.g. "staging-eu").
- Creating, renaming, or marking as production needs `datasources.manage`.
- Removing production protection or deleting a production environment also needs
  `org.manage` (only Owners by default): it is the riskiest change to an environment.
- An environment that still has databases cannot be deleted. Move or remove them first.
- Deleting an environment also deletes the per-environment role overrides for it.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Datasource, Environment
from app.rbac.catalog import Permission


class EnvironmentNotFoundError(Exception):
    pass


class NameTakenError(Exception):
    pass


class NotEmptyError(Exception):
    def __init__(self, datasources: int) -> None:
        super().__init__(datasources)
        self.datasources = datasources


class NeedsOrgManageError(Exception):
    pass


@dataclass(slots=True)
class EnvironmentInfo:
    environment: Environment
    datasource_count: int


def _counts_query(tenant_id: uuid.UUID) -> Any:
    count = (
        select(func.count())
        .select_from(Datasource)
        .where(Datasource.environment_id == Environment.id)
        .correlate(Environment)
        .scalar_subquery()
    )
    return select(Environment, count).where(Environment.tenant_id == tenant_id)


async def list_environments(session: AsyncSession, tenant_id: uuid.UUID) -> list[EnvironmentInfo]:
    rows = await session.execute(
        _counts_query(tenant_id).order_by(Environment.is_production.desc(), Environment.name)
    )
    return [EnvironmentInfo(environment=e, datasource_count=n) for e, n in rows.all()]


async def get_environment(
    session: AsyncSession, tenant_id: uuid.UUID, environment_id: uuid.UUID, *, lock: bool = False
) -> EnvironmentInfo:
    query = _counts_query(tenant_id).where(Environment.id == environment_id)
    if lock:
        query = query.with_for_update(of=Environment)
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise EnvironmentNotFoundError
    return EnvironmentInfo(environment=row[0], datasource_count=row[1])


async def _save(session: AsyncSession, env: Environment) -> None:
    try:
        async with session.begin_nested():
            session.add(env)
            await session.flush()
    except IntegrityError as exc:
        raise NameTakenError from exc


async def create_environment(
    session: AsyncSession, *, tenant_id: uuid.UUID, name: str, is_production: bool
) -> Environment:
    env = Environment(tenant_id=tenant_id, name=name, is_production=is_production)
    await _save(session, env)
    await session.refresh(env)
    return env


async def update_environment(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    environment_id: uuid.UUID,
    actor_permissions: frozenset[str],
    name: str | None,
    is_production: bool | None,
) -> tuple[EnvironmentInfo, dict[str, Any]]:
    info = await get_environment(session, tenant_id, environment_id, lock=True)
    env = info.environment
    changes: dict[str, Any] = {}

    if is_production is not None and is_production != env.is_production:
        if env.is_production and Permission.ORG_MANAGE not in actor_permissions:
            raise NeedsOrgManageError
        changes["is_production"] = {"from": env.is_production, "to": is_production}
        env.is_production = is_production

    if name is not None and name != env.name:
        changes["name"] = {"from": env.name, "to": name}
        env.name = name

    if changes:
        await _save(session, env)
    return info, changes


async def delete_environment(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    environment_id: uuid.UUID,
    actor_permissions: frozenset[str],
) -> Environment:
    info = await get_environment(session, tenant_id, environment_id, lock=True)
    env = info.environment
    if env.is_production and Permission.ORG_MANAGE not in actor_permissions:
        raise NeedsOrgManageError
    if info.datasource_count:
        raise NotEmptyError(info.datasource_count)
    await session.delete(env)
    await session.flush()
    return env
