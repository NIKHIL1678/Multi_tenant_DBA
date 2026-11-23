"""Starting, running and finishing agent runs.

start()    checks AI is set up, the person has no other run going and the company is within
           its daily limits; saves the question and a queued run; schedules execute().
execute()  runs the graph in the background (one API process today) with a time limit, writes
           progress steps as they happen, then saves the answer, verified findings, the
           assistant message, the conversation context and token use.

A run that cannot finish ends as failed with a message a person can act on; internal errors
are logged, never shown. Runs left queued or running by a restart are closed at startup.
"""

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.graph import build_graph
from app.ai.llm import LLM, AIUnavailableError, GroqLLM, Usage
from app.ai.problems import explain_question
from app.ai.toolbox import LiveToolbox
from app.ai.verify import VerifiedFinding, action_json
from app.core.config import get_settings
from app.core.db import SessionFactory
from app.gateway.hub import ConnectorHub
from app.models import (
    AgentRun,
    AiConversation,
    AiMessage,
    AiUsageDaily,
    Datasource,
    Finding,
)
from app.models.enums import AgentRunKind, AgentRunStatus, MessageRole

logger = logging.getLogger(__name__)

ACTIVE = (AgentRunStatus.QUEUED, AgentRunStatus.RUNNING)
STUCK_AFTER = timedelta(minutes=15)  # an older "active" run does not block a new one
HISTORY_MESSAGES = 10


class AIDisabledError(Exception):
    """GROQ_API_KEY is not set."""


class BusyError(Exception):
    """The person already has a run going."""


class LimitReachedError(Exception):
    """The company used its AI runs or tokens for today."""


class NotFoundError(Exception):
    """Conversation not found for this person and datasource."""


# ---- the model (replaceable in tests) -----------------------------------------------------------

_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm  # one client (with its connection pool) per process
    if _llm is None:
        _llm = GroqLLM(get_settings())
    return _llm


LlmFactory = Callable[[], LLM]
llm_factory: LlmFactory = get_llm


# ---- starting ---------------------------------------------------------------------------------


def _today() -> date:
    return datetime.now(UTC).date()


async def usage_today(session: AsyncSession, tenant_id: uuid.UUID) -> AiUsageDaily | None:
    return await session.get(AiUsageDaily, (tenant_id, _today()))


async def _check_limits(session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    settings = get_settings()
    if not settings.ai_enabled:
        raise AIDisabledError
    active = await session.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(
            AgentRun.user_id == user_id,
            AgentRun.status.in_([s.value for s in ACTIVE]),
            AgentRun.created_at > datetime.now(UTC) - STUCK_AFTER,
        )
    )
    if active:
        raise BusyError
    used = await usage_today(session, tenant_id)
    if used is not None and (
        used.runs >= settings.ai_daily_runs
        or used.input_tokens + used.output_tokens >= settings.ai_daily_tokens
    ):
        raise LimitReachedError


async def _conversation(
    session: AsyncSession,
    *,
    conversation_id: uuid.UUID | None,
    ds: Datasource,
    user_id: uuid.UUID,
    title: str,
) -> AiConversation:
    if conversation_id is not None:
        conv = await session.get(AiConversation, conversation_id)
        if conv is None or (conv.datasource_id, conv.user_id) != (ds.id, user_id):
            raise NotFoundError
        return conv
    conv = AiConversation(
        tenant_id=ds.tenant_id, datasource_id=ds.id, user_id=user_id, title=title[:120], context={}
    )
    session.add(conv)
    await session.flush()
    return conv


async def _last_question(session: AsyncSession, conversation_id: uuid.UUID) -> str | None:
    return await session.scalar(
        select(AiMessage.content)
        .where(
            AiMessage.conversation_id == conversation_id,
            AiMessage.role == MessageRole.USER,
            ~AiMessage.content.startswith("Table: "),
        )
        .order_by(AiMessage.created_at.desc())
        .limit(1)
    )


async def start(
    session: AsyncSession,
    *,
    ds: Datasource,
    user_id: uuid.UUID,
    kind: AgentRunKind,
    message: str | None = None,
    problem: str | None = None,
    problem_title: str | None = None,
    conversation_id: uuid.UUID | None = None,
    table: str | None = None,
) -> AgentRun:
    """Validate and queue a run (committed). The caller then calls schedule(run.id)."""
    await _check_limits(session, ds.tenant_id, user_id)

    if kind == AgentRunKind.EXPLAIN:
        question = explain_question(problem_title or problem or "")
        conv = await _conversation(
            session, conversation_id=None, ds=ds, user_id=user_id, title=problem_title or question
        )
        shown = f"Explain: {problem_title or problem}"
    elif table is not None:
        # The person picked a table offered by "Which table do you mean?": same question again.
        if conversation_id is None:
            raise NotFoundError
        conv = await _conversation(
            session, conversation_id=conversation_id, ds=ds, user_id=user_id, title=""
        )
        previous = await _last_question(session, conv.id)
        if previous is None:
            raise NotFoundError
        question, shown = previous, f"Table: {table}"
        conv.context = {**conv.context, "table": table}
    else:
        question = (message or "").strip()
        conv = await _conversation(
            session, conversation_id=conversation_id, ds=ds, user_id=user_id, title=question
        )
        shown = question

    run = AgentRun(
        tenant_id=ds.tenant_id,
        datasource_id=ds.id,
        user_id=user_id,
        conversation_id=conv.id,
        kind=kind,
        status=AgentRunStatus.QUEUED,
        question=question,
        problem=problem,
        steps=[],
        notes=[],
        follow_ups=[],
    )
    session.add(run)
    await session.flush()
    session.add(
        AiMessage(
            tenant_id=ds.tenant_id,
            conversation_id=conv.id,
            role=MessageRole.USER,
            content=shown,
            run_id=run.id,
        )
    )
    conv.updated_at = datetime.now(UTC)
    await _count_usage(session, ds.tenant_id, runs=1)
    await session.commit()
    return run


async def _count_usage(
    session: AsyncSession, tenant_id: uuid.UUID, *, runs: int = 0, usage: Usage | None = None
) -> None:
    inp = usage.input_tokens if usage else 0
    out = usage.output_tokens if usage else 0
    stmt = insert(AiUsageDaily).values(
        tenant_id=tenant_id, day=_today(), runs=runs, input_tokens=inp, output_tokens=out
    )
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[AiUsageDaily.tenant_id, AiUsageDaily.day],
            set_={
                "runs": AiUsageDaily.runs + stmt.excluded.runs,
                "input_tokens": AiUsageDaily.input_tokens + stmt.excluded.input_tokens,
                "output_tokens": AiUsageDaily.output_tokens + stmt.excluded.output_tokens,
            },
        )
    )


# ---- running ----------------------------------------------------------------------------------

_tasks: set[asyncio.Task[None]] = set()


def schedule(run_id: uuid.UUID, sessions: SessionFactory, hub: ConnectorHub) -> None:
    task = asyncio.create_task(execute(run_id, sessions, hub), name=f"agent-run-{run_id}")
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def drain() -> None:
    """Wait for every scheduled run (tests, shutdown)."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


def fingerprint(v: VerifiedFinding) -> str:
    key = f"{v.finding.category.value}|{v.table or ''}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


async def execute(run_id: uuid.UUID, sessions: SessionFactory, hub: ConnectorHub) -> None:
    settings = get_settings()
    lock = asyncio.Lock()  # one write at a time: parallel specialists report progress too

    async with sessions() as session:
        run = await session.get(AgentRun, run_id)
        if run is None or run.status != AgentRunStatus.QUEUED:
            return
        ds = await session.get(Datasource, run.datasource_id)
        conv = (
            await session.get(AiConversation, run.conversation_id) if run.conversation_id else None
        )
        if ds is None:
            return
        history: list[dict[str, str]] = []
        if conv is not None:
            rows = (
                await session.execute(
                    select(AiMessage.role, AiMessage.content)
                    .where(
                        AiMessage.conversation_id == conv.id,
                        or_(AiMessage.run_id.is_(None), AiMessage.run_id != run.id),
                    )
                    .order_by(AiMessage.created_at.desc())
                    .limit(HISTORY_MESSAGES)
                )
            ).all()
            history = [{"role": r.role, "content": r.content} for r in reversed(rows)]
        state: dict[str, Any] = {
            "kind": run.kind,
            "question": run.question,
            "problem": run.problem,
            "engine": ds.engine,
            "server": ds.local_name,
            "history": history,
            "context": dict(conv.context) if conv else {},
        }
        run.status = AgentRunStatus.RUNNING
        await session.commit()

    async def progress(key: str, label: str) -> None:
        async with lock, sessions() as s:
            current = await s.get(AgentRun, run_id)
            if current is not None:
                current.steps = [*current.steps, {"key": key, "label": label}]
                await s.commit()

    usage = Usage()
    result: dict[str, Any] | None = None
    error: str | None = None
    try:
        graph = build_graph(llm_factory(), LiveToolbox(sessions, hub, ds.id), usage, progress)
        result = await asyncio.wait_for(graph.ainvoke(state), settings.ai_run_timeout_seconds)
    except AIUnavailableError as exc:
        error = str(exc)
    except TimeoutError:
        error = "The answer took too long. Try a narrower question."
    except Exception:
        logger.exception("agent run failed", extra={"run_id": str(run_id)})
        error = "Something went wrong while answering. Please try again."

    async with lock, sessions() as session:
        run = await session.get(AgentRun, run_id)
        if run is None:
            return
        run.input_tokens, run.output_tokens = usage.input_tokens, usage.output_tokens
        run.model = ", ".join(usage.models) or None
        run.finished_at = datetime.now(UTC)
        await _count_usage(session, run.tenant_id, usage=usage)
        if result is None:
            run.status, run.error = AgentRunStatus.FAILED, error
            await session.commit()
            return

        run.answer = result.get("answer")
        run.follow_ups = list(result.get("follow_ups", []))
        run.notes = list(dict.fromkeys(result.get("notes", [])))
        run.clarification = result.get("clarification")
        run.status = AgentRunStatus.NEEDS_INPUT if run.clarification else AgentRunStatus.DONE
        for v in result.get("verified", []):
            session.add(
                Finding(
                    tenant_id=run.tenant_id,
                    datasource_id=run.datasource_id,
                    run_id=run.id,
                    specialist=v.specialist,
                    severity=v.finding.severity,
                    category=v.finding.category,
                    title=v.finding.title,
                    explanation=v.finding.explanation,
                    evidence=[_evidence(result, e) for e in v.evidence],
                    table_name=v.table,
                    action=action_json(v.action),
                    fingerprint=fingerprint(v),
                )
            )
        if run.conversation_id is not None:
            conv = await session.get(AiConversation, run.conversation_id)
            if conv is not None:
                if "context_out" in result:
                    conv.context = result["context_out"]
                conv.updated_at = datetime.now(UTC)
            if run.answer:
                session.add(
                    AiMessage(
                        tenant_id=run.tenant_id,
                        conversation_id=run.conversation_id,
                        role=MessageRole.ASSISTANT,
                        content=run.answer,
                        run_id=run.id,
                    )
                )
        await session.commit()


def _evidence(result: dict[str, Any], fact_id: str) -> dict[str, str]:
    ev = result.get("evidence")
    fact = ev.facts.get(fact_id) if ev is not None else None
    return {"id": fact_id, "summary": fact.summary if fact else fact_id}


async def close_interrupted(session: AsyncSession) -> int:
    """At startup: runs that were queued or running when the process stopped cannot finish."""
    result = await session.execute(
        update(AgentRun)
        .where(AgentRun.status.in_([s.value for s in ACTIVE]))
        .values(
            status=AgentRunStatus.FAILED,
            error="Interrupted by a restart. Please ask again.",
            finished_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return result.rowcount or 0  # type: ignore[attr-defined]
