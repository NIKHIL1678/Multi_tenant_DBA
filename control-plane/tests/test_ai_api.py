"""Ask AI and Explain through the API: the real runner, toolbox, Verifier and database, with a
fake connector hub and a scripted model. Runs are executed right after the request (tests share
one database session, so nothing runs in parallel with a request)."""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import runner
from app.ai.outputs import ActionOut, AnswerOut, Category, FindingOut, PlanOut, SpecialistOut
from app.core.config import get_settings
from app.core.db import get_session_factory
from app.gateway.hub import get_hub
from app.models import AgentRun, AiConversation, AiUsageDaily, Finding
from app.models.enums import AgentRunStatus, FindingSeverity, Specialist
from tests.ai_fakes import FakeLLM, unavailable
from tests.factories import make_tenant, make_user
from tests.test_collectors import TABLE_INDEX, FakeHub
from tests.test_datasources import R, hdr, member, world

ANSWER = AnswerOut(answer="Lookups by employee and day read every row (Q1).", follow_ups=["More?"])
INDEX_SQL = "CREATE INDEX idx_att_emp_day ON zipzy_hrm.attendance (emp_id, day)"


def plan(*specialists: Specialist, table: str | None = None, **kw: Any) -> PlanOut:
    return PlanOut(
        about_this_database=True,
        asks_for_row_data=False,
        specialists=list(specialists),
        table=table,
        period=kw.get("period"),
    )


def missing_index(evidence: list[str], statement: str | None = INDEX_SQL) -> SpecialistOut:
    return SpecialistOut(
        findings=[
            FindingOut(
                severity=FindingSeverity.HIGH,
                category=Category.MISSING_INDEX,
                title="Attendance lookups read 200,000 rows each",
                explanation="Each lookup by employee and day scans the table.",
                evidence=evidence,
                table="zipzy_hrm.attendance",
                action=None
                if statement is None
                else ActionOut(statement=statement, reason="Read a few rows", risk="low"),
            )
        ],
        summary="A missing index on attendance.",
    )


class Harness:
    def __init__(self, api: AsyncClient, db: AsyncSession, hub: FakeHub) -> None:
        self.api, self.db, self.hub = api, db, hub
        self.scheduled: list[uuid.UUID] = []

    @asynccontextmanager
    async def sessions(self) -> AsyncIterator[AsyncSession]:
        yield self.db  # the test's rolled-back session, never closed here

    async def run_scheduled(self) -> None:
        while self.scheduled:
            await runner.execute(self.scheduled.pop(0), self.sessions, self.hub)  # type: ignore[arg-type]


@pytest.fixture
def ai(api: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> Iterator[Harness]:
    from app.main import app

    monkeypatch.setattr(get_settings(), "groq_api_key", SecretStr("gsk_test"))
    h = Harness(api, db, FakeHub())
    app.dependency_overrides[get_hub] = lambda: h.hub
    app.dependency_overrides[get_session_factory] = lambda: h.sessions
    monkeypatch.setattr(runner, "schedule", lambda run_id, s, hub: h.scheduled.append(run_id))
    yield h


def use_llm(monkeypatch: pytest.MonkeyPatch, llm: FakeLLM) -> FakeLLM:
    monkeypatch.setattr(runner, "llm_factory", lambda: llm)
    return llm


def runs_url(t: Any, ds: Any) -> str:
    return f"/v1/tenants/{t.id}/datasources/{ds.id}/ai/runs"


async def test_ask_a_question_and_get_a_checked_answer(
    ai: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await world(db)
    viewer, _ = await member(db, w.t, R.VIEWER)
    llm = use_llm(
        monkeypatch,
        FakeLLM(
            plan=plan(Specialist.QUERY, table="attendance"),
            specialist_query=missing_index(["Q1", "T1"]),
            answer=ANSWER,
        ),
    )
    r = await ai.api.post(
        runs_url(w.t, w.my_staging),
        headers=hdr(viewer),
        json={"kind": "chat", "message": "Why is attendance slow?"},
    )
    assert r.status_code == 202, r.text
    queued = r.json()
    assert queued["status"] == "queued" and queued["answer"] is None

    await ai.run_scheduled()
    run = (
        await ai.api.get(f"/v1/tenants/{w.t.id}/ai/runs/{queued['id']}", headers=hdr(viewer))
    ).json()
    assert run["status"] == "done", run
    assert run["answer"] == ANSWER.answer and run["follow_ups"] == ["More?"]
    assert [s["key"] for s in run["steps"]][:3] == ["plan", "resolve", "gather"]
    finding = run["findings"][0]
    assert finding["action"]["statement"] == INDEX_SQL and finding["action"]["risk"] == "low"
    assert finding["table"] == "zipzy_hrm.attendance" and finding["specialist"] == "query"
    assert {e["id"] for e in finding["evidence"]} == {"Q1", "T1"}
    assert "attendance" in next(e["summary"] for e in finding["evidence"] if e["id"] == "T1")

    # The connector was asked only for what the query specialist needs, plus the table list.
    assert {t for t, _ in ai.hub.calls} == {"table_index", "slow_queries", "table_stats", "indexes"}
    assert all(args == {"datasource": w.my_staging.local_name} for _, args in ai.hub.calls)

    # Conversation, context and usage are saved.
    conv = (
        await ai.api.get(
            f"/v1/tenants/{w.t.id}/ai/conversations/{run['conversation_id']}", headers=hdr(viewer)
        )
    ).json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    assert conv["context"] == {"table": "zipzy_hrm.attendance_*"}, "the monthly family was chosen"
    usage = await db.get(AiUsageDaily, (w.t.id, runner._today()))
    assert usage is not None and usage.runs == 1 and usage.input_tokens == 300
    assert sorted(llm.names()) == ["answer", "plan", "specialist_query"]

    listed = (
        await ai.api.get(
            f"/v1/tenants/{w.t.id}/datasources/{w.my_staging.id}/ai/conversations",
            headers=hdr(viewer),
        )
    ).json()
    assert [c["id"] for c in listed] == [run["conversation_id"]]


async def test_follow_up_continues_the_conversation(
    ai: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await world(db)
    llm = use_llm(
        monkeypatch,
        FakeLLM(
            plan=[plan(Specialist.QUERY, table="attendance"), plan(Specialist.QUERY)],
            specialist_query=missing_index(["Q1"]),
            answer=ANSWER,
        ),
    )
    first = (
        await ai.api.post(
            runs_url(w.t, w.my_staging),
            headers=hdr(w.owner),
            json={"kind": "chat", "message": "Why is attendance slow?"},
        )
    ).json()
    await ai.run_scheduled()
    second = await ai.api.post(
        runs_url(w.t, w.my_staging),
        headers=hdr(w.owner),
        json={
            "kind": "chat",
            "message": "Add an index to it",
            "conversation_id": first["conversation_id"],
        },
    )
    assert second.status_code == 202
    await ai.run_scheduled()
    # The second plan call saw the first question and answer, and the remembered table.
    second_plan = [c for c in llm.calls if c.name == "plan"][1]
    assert "Why is attendance slow?" in second_plan.user and "<context>" in second_plan.user
    assert "zipzy_hrm.attendance" in second_plan.user


async def test_explain_a_problem(
    ai: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await world(db)
    llm = use_llm(
        monkeypatch,
        FakeLLM(
            specialist_query=missing_index(["Q1"]),
            specialist_schema=SpecialistOut(findings=[], summary="Nothing else."),
            answer=ANSWER,
        ),
    )
    r = await ai.api.post(
        runs_url(w.t, w.my_staging),
        headers=hdr(w.owner),
        json={
            "kind": "explain",
            "problem": "noindex",
            "problem_title": "1 statement runs without a needed index",
        },
    )
    assert r.status_code == 202, r.text
    await ai.run_scheduled()
    run = (
        await ai.api.get(f"/v1/tenants/{w.t.id}/ai/runs/{r.json()['id']}", headers=hdr(w.owner))
    ).json()
    assert run["status"] == "done" and run["kind"] == "explain"
    assert "plan" not in llm.names()
    assert "without a needed index" in run["question"]
    conv = (
        await ai.api.get(
            f"/v1/tenants/{w.t.id}/ai/conversations/{run['conversation_id']}", headers=hdr(w.owner)
        )
    ).json()
    assert conv["messages"][0]["content"] == "Explain: 1 statement runs without a needed index"


async def test_which_table_then_the_choice(
    ai: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await world(db)
    ai.hub.answers["table_index"] = {
        **TABLE_INDEX,
        "total_tables": 2,
        "listed_tables": 2,
        "schemas": [
            {"name": "hrm", "tables": [["attendance", 10, 10]]},
            {"name": "payroll", "tables": [["attendance", 10, 10]]},
        ],
    }
    use_llm(
        monkeypatch,
        FakeLLM(
            plan=plan(Specialist.SCHEMA, table="attendance"),
            specialist_schema=SpecialistOut(findings=[], summary="Fine."),
            answer=ANSWER,
        ),
    )
    first = (
        await ai.api.post(
            runs_url(w.t, w.my_staging),
            headers=hdr(w.owner),
            json={"kind": "chat", "message": "Is attendance ok?"},
        )
    ).json()
    await ai.run_scheduled()
    asked = (
        await ai.api.get(f"/v1/tenants/{w.t.id}/ai/runs/{first['id']}", headers=hdr(w.owner))
    ).json()
    assert asked["status"] == "needs_input"
    assert {o["table"] for o in asked["clarification"]["options"]} == {
        "hrm.attendance",
        "payroll.attendance",
    }

    second = await ai.api.post(
        runs_url(w.t, w.my_staging),
        headers=hdr(w.owner),
        json={
            "kind": "chat",
            "table": "payroll.attendance",
            "conversation_id": first["conversation_id"],
        },
    )
    assert second.status_code == 202, second.text
    assert second.json()["question"] == "Is attendance ok?", "the original question is asked again"
    await ai.run_scheduled()
    done = (
        await ai.api.get(
            f"/v1/tenants/{w.t.id}/ai/runs/{second.json()['id']}", headers=hdr(w.owner)
        )
    ).json()
    assert done["status"] == "done"
    conv = await db.get(AiConversation, uuid.UUID(first["conversation_id"]))
    assert conv is not None and conv.context["table"] == "payroll.attendance"


async def test_model_failure_ends_the_run_with_a_reason(
    ai: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await world(db)
    use_llm(monkeypatch, FakeLLM(plan=unavailable("The Groq API key was refused.")))
    r = (
        await ai.api.post(
            runs_url(w.t, w.my_staging),
            headers=hdr(w.owner),
            json={"kind": "chat", "message": "How is it?"},
        )
    ).json()
    await ai.run_scheduled()
    run = (await ai.api.get(f"/v1/tenants/{w.t.id}/ai/runs/{r['id']}", headers=hdr(w.owner))).json()
    assert (run["status"], run["error"]) == ("failed", "The Groq API key was refused.")


async def test_offline_connector_uses_the_last_statistics(
    ai: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await world(db)
    ai.hub.online = False
    use_llm(monkeypatch, FakeLLM(plan=plan(Specialist.HEALTH), answer=ANSWER))
    r = (
        await ai.api.post(
            runs_url(w.t, w.my_staging),
            headers=hdr(w.owner),
            json={"kind": "chat", "message": "How is it?"},
        )
    ).json()
    await ai.run_scheduled()
    run = (await ai.api.get(f"/v1/tenants/{w.t.id}/ai/runs/{r['id']}", headers=hdr(w.owner))).json()
    assert run["status"] == "done", run
    assert any("offline" in n for n in run["notes"])
    assert any("not collected yet" in n for n in run["notes"])
    assert ai.hub.calls == []


async def test_who_may_ask_and_see(
    ai: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await world(db)
    use_llm(
        monkeypatch,
        FakeLLM(
            plan=plan(Specialist.HEALTH),
            specialist_health=SpecialistOut(findings=[], summary="ok"),
            answer=ANSWER,
        ),
    )
    r = (
        await ai.api.post(
            runs_url(w.t, w.my_staging),
            headers=hdr(w.owner),
            json={"kind": "chat", "message": "How is it?"},
        )
    ).json()
    await ai.run_scheduled()

    outsider = await make_user(db)
    other_tenant = await make_tenant(db)
    colleague, _ = await member(db, w.t, R.DBA)
    body = {"kind": "chat", "message": "x"}
    assert (
        await ai.api.post(runs_url(w.t, w.my_staging), headers=hdr(outsider), json=body)
    ).status_code == 404
    assert (
        await ai.api.post(
            f"/v1/tenants/{other_tenant.id}/datasources/{w.my_staging.id}/ai/runs",
            headers=hdr(w.owner),
            json=body,
        )
    ).status_code == 404
    # A colleague cannot read someone else's run or conversation.
    assert (
        await ai.api.get(f"/v1/tenants/{w.t.id}/ai/runs/{r['id']}", headers=hdr(colleague))
    ).status_code == 404
    assert (
        await ai.api.get(
            f"/v1/tenants/{w.t.id}/ai/conversations/{r['conversation_id']}", headers=hdr(colleague)
        )
    ).status_code == 404
    # Nor continue it.
    cont = await ai.api.post(
        runs_url(w.t, w.my_staging),
        headers=hdr(colleague),
        json={**body, "conversation_id": r["conversation_id"]},
    )
    assert cont.status_code == 404


async def test_limits_busy_disabled_and_bad_requests(
    ai: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await world(db)
    url_ = runs_url(w.t, w.my_staging)
    body = {"kind": "chat", "message": "How is it?"}
    use_llm(monkeypatch, FakeLLM())

    first = await ai.api.post(url_, headers=hdr(w.owner), json=body)
    assert first.status_code == 202
    busy = await ai.api.post(url_, headers=hdr(w.owner), json=body)  # first not run yet
    assert (busy.status_code, busy.json()["error"]["code"]) == (409, "ai_busy")
    ai.scheduled.clear()
    run = await db.get(AgentRun, uuid.UUID(first.json()["id"]))
    assert run is not None
    run.status = AgentRunStatus.DONE
    await db.flush()

    usage = await db.get(AiUsageDaily, (w.t.id, runner._today()))
    assert usage is not None
    usage.runs = get_settings().ai_daily_runs
    await db.flush()
    limited = await ai.api.post(url_, headers=hdr(w.owner), json=body)
    assert (limited.status_code, limited.json()["error"]["code"]) == (429, "ai_limit")
    status = (await ai.api.get(f"/v1/tenants/{w.t.id}/ai/status", headers=hdr(w.owner))).json()
    assert status["enabled"] is True and status["runs_today"] == status["runs_limit"]

    monkeypatch.setattr(get_settings(), "groq_api_key", SecretStr(""))
    off = await ai.api.post(url_, headers=hdr(w.owner), json=body)
    assert (off.status_code, off.json()["error"]["code"]) == (503, "ai_disabled")
    assert (await ai.api.get(f"/v1/tenants/{w.t.id}/ai/status", headers=hdr(w.owner))).json()[
        "enabled"
    ] is False

    for bad in (
        {"kind": "chat"},
        {"kind": "chat", "message": "x", "table": "a.b"},
        {"kind": "chat", "table": "a.b"},
        {"kind": "explain", "message": "x"},
        {"kind": "chat", "message": "x" * 2001},
    ):
        assert (await ai.api.post(url_, headers=hdr(w.owner), json=bad)).status_code == 422, bad
    monkeypatch.setattr(get_settings(), "groq_api_key", SecretStr("gsk_test"))
    usage.runs = 0
    await db.flush()
    unknown = await ai.api.post(
        url_, headers=hdr(w.owner), json={"kind": "explain", "problem": "nosuch"}
    )
    assert (unknown.status_code, unknown.json()["error"]["code"]) == (422, "unknown_problem")


async def test_runs_cut_off_by_a_restart_are_closed(
    ai: Harness, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    w = await world(db)
    use_llm(monkeypatch, FakeLLM())
    r = (
        await ai.api.post(
            runs_url(w.t, w.my_staging), headers=hdr(w.owner), json={"kind": "chat", "message": "x"}
        )
    ).json()
    assert await runner.close_interrupted(db) >= 1
    run = await db.get(AgentRun, uuid.UUID(r["id"]))
    assert run is not None
    await db.refresh(run)
    assert run.status == "failed" and "restart" in (run.error or "")
    # A closed run is never executed afterwards.
    await ai.run_scheduled()
    assert (await db.scalars(select(Finding).where(Finding.run_id == run.id))).all() == []


def test_every_dashboard_problem_can_be_explained() -> None:
    import re
    from pathlib import Path

    from app.ai.problems import PROBLEMS

    source = (
        Path(__file__).resolve().parents[2]
        / "dashboard/src/features/datasources/server/attention.ts"
    )
    ids = set(re.findall(r"id: '([a-z]+)'", source.read_text(encoding="utf-8")))
    assert ids and ids == set(PROBLEMS), f"dashboard {sorted(ids)} vs server {sorted(PROBLEMS)}"
