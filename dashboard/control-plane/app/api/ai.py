"""AI agents: Ask AI and Explain (docs/08-ai-agents.md).

GET  /v1/tenants/{tid}/ai/status                                   is AI set up; today's use
POST /v1/tenants/{tid}/datasources/{dsid}/ai/runs                   start a run -> 202
GET  /v1/tenants/{tid}/ai/runs/{run_id}                             progress / answer (poll)
GET  /v1/tenants/{tid}/ai/conversations                            my conversations, all servers
GET  /v1/tenants/{tid}/datasources/{dsid}/ai/conversations          my conversations, one server
GET  /v1/tenants/{tid}/ai/conversations/{conversation_id}           one, with messages and runs

Who: a person who can see the datasource (metadata.read in its environment) and read
findings there (findings.read). Runs and conversations are private to the person who started
them; anyone else gets "not found". Visibility is checked again on every read, so losing
access to an environment hides its conversations at once.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.ai import runner
from app.ai.problems import PROBLEMS
from app.api.datasources import _RULE_ERRORS, _translate
from app.api.errors import ApiError, forbidden, not_found
from app.auth.current_user import CurrentUser, DbSession
from app.auth.permissions import require_member
from app.core.config import get_settings
from app.core.db import SessionFactory, get_session_factory
from app.gateway.hub import ConnectorHub, get_hub
from app.models import AgentRun, AiConversation, AiMessage, Datasource, Environment, Finding
from app.models.enums import AgentRunKind
from app.rbac.catalog import Permission
from app.rbac.service import AccessContext, environments_with_permission
from app.schemas.ai import (
    AiStatusOut,
    ConversationDetailOut,
    ConversationListItem,
    ConversationOut,
    MessageOut,
    RunIn,
    RunOut,
)
from app.services import datasources as datasources_svc

router = APIRouter(prefix="/v1/tenants/{tenant_id}", tags=["ai"])

Member = Annotated[AccessContext, Depends(require_member)]
Sessions = Annotated[SessionFactory, Depends(get_session_factory)]
Hub = Annotated[ConnectorHub, Depends(get_hub)]

MAX_CONVERSATIONS = 30


async def _datasource_for_ai(
    session: DbSession, user: CurrentUser, tenant_id: uuid.UUID, datasource_id: uuid.UUID
) -> datasources_svc.DatasourceInfo:
    """Visible (metadata.read) and findings.read in its environment; else 404 / 403."""
    try:
        info = await datasources_svc.get_visible(
            session, user_id=user.user_id, tenant_id=tenant_id, datasource_id=datasource_id
        )
    except _RULE_ERRORS as exc:
        raise _translate(exc) from None
    access = await datasources_svc.access_in(
        session, user_id=user.user_id, tenant_id=tenant_id, environment_id=info.environment.id
    )
    if access is None or not access.has(Permission.FINDINGS_READ):
        raise forbidden("You cannot use AI on this database.")
    return info


async def _run_out(session: DbSession, run: AgentRun) -> RunOut:
    findings = (
        await session.scalars(
            select(Finding).where(Finding.run_id == run.id).order_by(Finding.created_at)
        )
    ).all()
    order = {"high": 0, "medium": 1, "low": 2}
    return RunOut.model_validate(
        {
            "id": run.id,
            "datasource_id": run.datasource_id,
            "conversation_id": run.conversation_id,
            "kind": run.kind,
            "status": run.status,
            "question": run.question,
            "steps": run.steps,
            "answer": run.answer,
            "follow_ups": run.follow_ups,
            "clarification": run.clarification,
            "notes": run.notes,
            "error": run.error,
            "findings": [
                {
                    "id": f.id,
                    "specialist": f.specialist,
                    "severity": f.severity,
                    "category": f.category,
                    "title": f.title,
                    "explanation": f.explanation,
                    "evidence": f.evidence,
                    "table": f.table_name,
                    "action": f.action,
                }
                for f in sorted(findings, key=lambda f: order[f.severity])
            ],
            "created_at": run.created_at,
            "finished_at": run.finished_at,
        }
    )


@router.get("/ai/status")
async def ai_status(tenant_id: uuid.UUID, _: Member, session: DbSession) -> AiStatusOut:
    s = get_settings()
    used = await runner.usage_today(session, tenant_id)
    return AiStatusOut(
        enabled=s.ai_enabled,
        model=s.ai_model,
        runs_today=used.runs if used else 0,
        runs_limit=s.ai_daily_runs,
        tokens_today=(used.input_tokens + used.output_tokens) if used else 0,
        tokens_limit=s.ai_daily_tokens,
    )


@router.post("/datasources/{datasource_id}/ai/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    tenant_id: uuid.UUID,
    datasource_id: uuid.UUID,
    body: RunIn,
    _: Member,
    user: CurrentUser,
    session: DbSession,
    sessions: Sessions,
    hub: Hub,
) -> RunOut:
    info = await _datasource_for_ai(session, user, tenant_id, datasource_id)
    if body.kind == AgentRunKind.EXPLAIN and body.problem not in PROBLEMS:
        raise ApiError(422, "unknown_problem", "This problem cannot be explained.")
    try:
        run = await runner.start(
            session,
            ds=info.datasource,
            user_id=user.user_id,
            kind=body.kind,
            message=body.message,
            problem=body.problem,
            problem_title=body.problem_title,
            conversation_id=body.conversation_id,
            table=body.table,
        )
    except runner.AIDisabledError:
        raise ApiError(503, "ai_disabled", "AI is not set up on this server.") from None
    except runner.BusyError:
        raise ApiError(
            409, "ai_busy", "You already have a question being answered. Wait for it first."
        ) from None
    except runner.LimitReachedError:
        raise ApiError(
            429,
            "ai_limit",
            "Your company has used today's AI allowance. It resets at midnight UTC.",
        ) from None
    except runner.NotFoundError:
        raise not_found("Conversation") from None
    runner.schedule(run.id, sessions, hub)
    return await _run_out(session, run)


async def _own_run(
    session: DbSession, user: CurrentUser, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> AgentRun:
    run = await session.get(AgentRun, run_id)
    if run is None or run.tenant_id != tenant_id or run.user_id != user.user_id:
        raise not_found("Run")
    await _datasource_for_ai(session, user, tenant_id, run.datasource_id)
    return run


@router.get("/ai/runs/{run_id}")
async def get_run(
    tenant_id: uuid.UUID, run_id: uuid.UUID, _: Member, user: CurrentUser, session: DbSession
) -> RunOut:
    run = await _own_run(session, user, tenant_id, run_id)
    await session.refresh(run)  # progress is written by the background run
    return await _run_out(session, run)


@router.get("/ai/conversations")
async def list_all_conversations(
    tenant_id: uuid.UUID, _: Member, user: CurrentUser, session: DbSession
) -> list[ConversationListItem]:
    """My conversations about every server I may still ask about (newest first)."""
    may_see = await environments_with_permission(
        session, user_id=user.user_id, tenant_id=tenant_id, permission=Permission.METADATA_READ
    )
    may_read = await environments_with_permission(
        session, user_id=user.user_id, tenant_id=tenant_id, permission=Permission.FINDINGS_READ
    )
    allowed = may_see & may_read
    if not allowed:
        return []
    rows = await session.execute(
        select(AiConversation, Datasource, Environment)
        .join(Datasource, Datasource.id == AiConversation.datasource_id)
        .join(Environment, Environment.id == Datasource.environment_id)
        .where(
            AiConversation.tenant_id == tenant_id,
            AiConversation.user_id == user.user_id,
            Datasource.tenant_id == tenant_id,
            Datasource.environment_id.in_(allowed),
        )
        .order_by(AiConversation.updated_at.desc())
        .limit(MAX_CONVERSATIONS)
    )
    return [
        ConversationListItem(
            id=c.id,
            datasource_id=c.datasource_id,
            title=c.title,
            context={k: str(v) for k, v in c.context.items()},
            updated_at=c.updated_at,
            datasource_name=ds.local_name,
            engine=ds.engine,
            environment_name=env.name,
            is_production=env.is_production,
        )
        for c, ds, env in rows
    ]


@router.get("/datasources/{datasource_id}/ai/conversations")
async def list_conversations(
    tenant_id: uuid.UUID,
    datasource_id: uuid.UUID,
    _: Member,
    user: CurrentUser,
    session: DbSession,
) -> list[ConversationOut]:
    info = await _datasource_for_ai(session, user, tenant_id, datasource_id)
    rows = await session.scalars(
        select(AiConversation)
        .where(
            AiConversation.datasource_id == info.datasource.id,
            AiConversation.user_id == user.user_id,
        )
        .order_by(AiConversation.updated_at.desc())
        .limit(MAX_CONVERSATIONS)
    )
    return [ConversationOut.model_validate(c, from_attributes=True) for c in rows]


@router.get("/ai/conversations/{conversation_id}")
async def get_conversation(
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    _: Member,
    user: CurrentUser,
    session: DbSession,
) -> ConversationDetailOut:
    conv = await session.get(AiConversation, conversation_id)
    if conv is None or conv.tenant_id != tenant_id or conv.user_id != user.user_id:
        raise not_found("Conversation")
    await _datasource_for_ai(session, user, tenant_id, conv.datasource_id)
    await session.refresh(conv)
    messages = (
        await session.scalars(
            select(AiMessage)
            .where(AiMessage.conversation_id == conv.id)
            .order_by(AiMessage.created_at, AiMessage.role.desc())
        )
    ).all()
    runs = (
        await session.scalars(
            select(AgentRun)
            .where(AgentRun.conversation_id == conv.id)
            .order_by(AgentRun.created_at)
        )
    ).all()
    return ConversationDetailOut(
        id=conv.id,
        datasource_id=conv.datasource_id,
        title=conv.title,
        context={k: str(v) for k, v in conv.context.items()},
        updated_at=conv.updated_at,
        messages=[MessageOut.model_validate(m, from_attributes=True) for m in messages],
        runs=[await _run_out(session, r) for r in runs],
    )
