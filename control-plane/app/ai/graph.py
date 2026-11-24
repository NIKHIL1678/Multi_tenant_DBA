"""The agent graph (LangGraph): plan, resolve, gather, specialists, verify, compose.

    plan        chat: the orchestrator (model) decides specialists, table words and period.
                explain: the problem decides the specialists (no model call).
    resolve     the table the question is about, by search among all tables (no model call).
                Two equally good matches end the run with a question and buttons.
    gather      code asks the connector for fresh statistics and turns them into facts.
    specialist  one model call per chosen specialist, in parallel, facts in, findings out.
    verify      code: evidence must exist, tables must exist, SQL must be on the allow-list.
    compose     the orchestrator (model) writes the reply from the verified findings.

The datasource is fixed before the graph starts; nothing in the graph can choose another.
The model never calls tools: code fetches the data (see ADR 0007).
"""

import operator
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from app.ai import facts, prompts
from app.ai.llm import LLM, AIUnavailableError, Usage
from app.ai.outputs import AnswerOut, Intent, PlanOut, SpecialistOut
from app.ai.problems import PROBLEMS
from app.ai.verify import VerifiedFinding, action_json, verify
from app.models.enums import AgentRunKind, Collector, Specialist
from app.schemas.snapshots import (
    HealthData,
    IndexesData,
    LocksData,
    SlowQueriesData,
    TableStatsData,
)
from app.services.table_search import Match, SearchResult

NEEDS: dict[Specialist, set[Collector]] = {
    Specialist.HEALTH: {Collector.HEALTH, Collector.LOCKS},
    Specialist.QUERY: {Collector.SLOW_QUERIES, Collector.TABLE_STATS, Collector.INDEXES},
    Specialist.SCHEMA: {Collector.TABLE_STATS, Collector.INDEXES},
}
FACTS_FOR: dict[Specialist, tuple[str, ...]] = {
    Specialist.HEALTH: ("H", "L"),
    Specialist.QUERY: ("Q", "T", "I"),
    Specialist.SCHEMA: ("T", "I"),
}
LABELS: dict[Specialist, str] = {
    Specialist.HEALTH: "Checking health and locks",
    Specialist.QUERY: "Checking slow queries",
    Specialist.SCHEMA: "Checking tables and indexes",
}
MAX_OPTIONS = 4  # tables offered when the question is ambiguous

OFF_TOPIC = (
    "I can help with this server's health, performance, tables, indexes, queries and locks. "
    "That question is about something else."
)
NO_ROWS = (
    "I only see statistics and structure, not the rows inside tables, so I cannot show stored "
    "values such as records, people or amounts. I can tell you how a table is used: its size, "
    "indexes and slow statements."
)
STARTERS = [
    "How is this server doing?",
    "Which statements are slowest, and why?",
    "Are there indexes I could remove?",
]


def greeting(server: str) -> str:
    return (
        f"Hello! I look after {server}. Ask me how it is doing, which statements are slow and "
        "why, or which tables and indexes need attention. I read its statistics, never the rows "
        "inside tables."
    )


def table_starters(words: str) -> list[str]:
    return [f"How is the {words} table doing?", f"Is the {words} table missing an index?"]


@dataclass(slots=True)
class Snapshots:
    health: HealthData | None = None
    locks: LocksData | None = None
    tables: TableStatsData | None = None
    indexes: IndexesData | None = None
    queries: SlowQueriesData | None = None
    notes: list[str] = field(default_factory=list)


class Toolbox(Protocol):
    """What the graph may ask for, all for the one datasource of the run."""

    async def gather(self, collectors: set[Collector]) -> Snapshots: ...

    async def find_tables(self, words: str, period: str | None) -> SearchResult | None: ...

    async def table_named(self, name: str, period: str | None) -> Match | None: ...


Progress = Callable[[str, str], Awaitable[None]]


class RunState(TypedDict, total=False):
    # fixed when the run starts
    kind: str
    question: str
    problem: str | None
    engine: str
    server: str
    history: list[dict[str, str]]
    context: dict[str, Any]  # {"table": "hrm.attendance_*", "period": "2026-11"}
    # filled by the nodes
    specialists: list[str]
    table_words: str | None
    period: str | None
    focus: list[str]  # "schema.table", lower case
    context_out: dict[str, Any]
    evidence: facts.Evidence
    reports: Annotated[list[dict[str, Any]], operator.add]
    verified: list[VerifiedFinding]
    notes: Annotated[list[str], operator.add]
    answer: str
    follow_ups: list[str]
    clarification: dict[str, Any] | None
    done: bool


class _SpecialistTask(TypedDict):
    specialist: str
    question: str
    engine: str
    server: str
    facts: dict[str, Any]
    notes: list[str]


def _period(value: str | None) -> str | None:
    """Only "YYYY" or "YYYY-MM" (month 01-12) count; anything else is ignored."""
    if value is None:
        return None
    value = value.strip()
    if len(value) == 4 and value.isdigit():
        return value
    if len(value) == 7 and value[4] == "-" and value[:4].isdigit() and value[5:].isdigit():
        return value if 1 <= int(value[5:]) <= 12 else None
    return None


def _focus_of(match: Match) -> list[str]:
    return [facts.qualified(t.schema, t.name).lower() for t in match.tables]


def _label(match: Match) -> str:
    name = f"{match.schema}.{match.name}"
    return f"{name} ({match.table_count} tables)" if match.kind == "family" else name


def build_graph(llm: LLM, tools: Toolbox, usage: Usage, progress: Progress) -> Any:
    async def ask(system: str, user: str, output: type[Any], name: str) -> Any:
        value, used = await llm.structured(system=system, user=user, output=output, name=name)
        usage.add(used)
        return value

    # ---- plan ----------------------------------------------------------------------------
    async def plan(state: RunState) -> dict[str, Any]:
        await progress("plan", "Understanding the question")
        context = state.get("context") or {}
        if state["kind"] == AgentRunKind.EXPLAIN:
            chosen = PROBLEMS[state["problem"] or ""]
            return {"specialists": [s.value for s in chosen], "table_words": None, "period": None}

        out: PlanOut = await ask(
            prompts.plan_system(state["engine"], state["server"], datetime.now(UTC).date()),
            prompts.plan_user(state["question"], state.get("history", []), context),
            PlanOut,
            "plan",
        )
        if out.intent == Intent.GREETING:
            return {"answer": greeting(state["server"]), "follow_ups": STARTERS, "done": True}
        if out.intent == Intent.ROW_DATA:
            words = (out.table or "").strip()
            follow_ups = table_starters(words) if words else STARTERS[:2]
            return {"answer": NO_ROWS, "follow_ups": follow_ups, "done": True}
        if out.intent != Intent.DATABASE:
            return {"answer": OFF_TOPIC, "follow_ups": STARTERS, "done": True}
        specialists = [s.value for s in dict.fromkeys(out.specialists)] or [
            s.value for s in Specialist
        ]
        return {
            "specialists": specialists,
            "table_words": out.table,
            "period": _period(out.period) or context.get("period"),
        }

    # ---- resolve the table -----------------------------------------------------------------
    async def resolve(state: RunState) -> dict[str, Any]:
        context = dict(state.get("context") or {})
        words, period = state.get("table_words"), state.get("period")
        chosen: Match | None = None
        notes: list[str] = []
        if words:
            await progress("resolve", "Finding the table")
            result = await tools.find_tables(words, period)
            remembered = str(context.get("table", "")).lower()
            again = (
                next(
                    (m for m in result.matches if f"{m.schema}.{m.name}".lower() == remembered),
                    None,
                )
                if result is not None and remembered
                else None
            )
            if result is None:
                notes.append("The list of tables is not available, so no table was singled out.")
            elif again is not None:
                chosen = again  # the table this conversation already settled on
            elif not result.matches:
                notes.append(f"No table matches “{words}”.")
            elif result.ambiguous:
                options = [
                    {"label": _label(m), "table": f"{m.schema}.{m.name}"}
                    for m in result.matches[:MAX_OPTIONS]
                ]
                return {
                    "clarification": {"question": "Which table do you mean?", "options": options},
                    "answer": "Which table do you mean?",
                    "follow_ups": [],
                    "done": True,
                }
            else:
                chosen = result.matches[0]
            if result is not None:
                notes.extend(result.notes)
        elif context.get("table"):
            chosen = await tools.table_named(str(context["table"]), period)
            if chosen is None:
                notes.append(f"The table {context['table']} is no longer on this server.")
        if chosen is not None:
            context["table"] = f"{chosen.schema}.{chosen.name}"
        if period:
            context["period"] = period
        return {
            "focus": _focus_of(chosen) if chosen else [],
            "context_out": context,
            "notes": notes,
        }

    # ---- gather ----------------------------------------------------------------------------
    async def gather(state: RunState) -> dict[str, Any]:
        await progress("gather", "Reading statistics")
        wanted: set[Collector] = set()
        for s in state["specialists"]:
            wanted |= NEEDS[Specialist(s)]
        snaps = await tools.gather(wanted)
        focus = set(state.get("focus", []))
        ev = facts.Evidence()
        if snaps.health:
            facts.add_health(ev, snaps.health)
        if snaps.locks:
            facts.add_locks(ev, snaps.locks)
        if snaps.tables:
            facts.add_tables(ev, snaps.tables, focus)
        if snaps.indexes:
            facts.add_indexes(ev, snaps.indexes, focus)
        if snaps.queries:
            facts.add_queries(ev, snaps.queries, focus)
        return {"evidence": ev, "notes": snaps.notes + ev.notes}

    def fan_out(state: RunState) -> list[Send]:
        ev = state["evidence"]
        question = state["question"]
        if state.get("focus"):
            question += f"\n(The question is about: {', '.join(state['focus'][:5])})"
        return [
            Send(
                "specialist",
                _SpecialistTask(
                    specialist=s,
                    question=question,
                    engine=state["engine"],
                    server=state["server"],
                    facts=ev.for_model(FACTS_FOR[Specialist(s)]),
                    notes=list(state.get("notes", [])),
                ),
            )
            for s in state["specialists"]
        ]

    # ---- specialists -----------------------------------------------------------------------
    async def specialist(task: _SpecialistTask) -> dict[str, Any]:
        who = Specialist(task["specialist"])
        await progress(f"specialist:{who.value}", LABELS[who])
        if not task["facts"]:
            return {
                "reports": [{"specialist": who.value, "findings": [], "summary": "No data."}],
                "notes": [f"There were no statistics for the {who.value} check."],
            }
        try:
            out: SpecialistOut = await ask(
                prompts.specialist_system(who, task["engine"], task["server"]),
                prompts.specialist_user(task["question"], task["facts"], task["notes"]),
                SpecialistOut,
                f"specialist_{who.value}",
            )
        except AIUnavailableError as exc:
            return {
                "reports": [
                    {"specialist": who.value, "findings": [], "summary": "", "failed": True}
                ],
                "notes": [f"The {who.value} check could not finish: {exc}"],
            }
        return {
            "reports": [{"specialist": who.value, "findings": out.findings, "summary": out.summary}]
        }

    # ---- verify ----------------------------------------------------------------------------
    async def check(state: RunState) -> dict[str, Any]:
        await progress("verify", "Checking the findings")
        reports = state.get("reports", [])
        if reports and all(r.get("failed") for r in reports):
            raise AIUnavailableError("The AI service could not finish any check.")
        kept: dict[tuple[str, str | None], VerifiedFinding] = {}
        notes: list[str] = []
        for report in reports:
            verified, dropped = verify(report["findings"], state["engine"], state["evidence"])
            notes.extend(dropped)
            for v in verified:
                v.specialist = report["specialist"]
                key = (v.finding.category.value, v.table)
                rank = {"high": 0, "medium": 1, "low": 2}
                if key not in kept or rank[v.finding.severity] < rank[kept[key].finding.severity]:
                    kept[key] = v
        return {"verified": list(kept.values()), "notes": notes}

    # ---- compose ---------------------------------------------------------------------------
    async def compose(state: RunState) -> dict[str, Any]:
        await progress("compose", "Writing the answer")
        findings = [
            {
                "severity": v.finding.severity.value,
                "title": v.finding.title,
                "explanation": v.finding.explanation,
                "evidence": v.evidence,
                "table": v.table,
                "suggested_statement": action_json(v.action) is not None,
            }
            for v in state.get("verified", [])
        ]
        summaries = {
            r["specialist"]: r["summary"] for r in state.get("reports", []) if r["summary"]
        }
        out: AnswerOut = await ask(
            prompts.compose_system(state["engine"], state["server"]),
            prompts.compose_user(
                state["question"],
                state.get("history", []),
                findings,
                summaries,
                list(dict.fromkeys(state.get("notes", []))),
            ),
            AnswerOut,
            "answer",
        )
        return {"answer": out.answer, "follow_ups": out.follow_ups, "done": True}

    def after_plan(state: RunState) -> str:
        return END if state.get("done") else "resolve"

    def after_resolve(state: RunState) -> str:
        return END if state.get("done") else "gather"

    graph = StateGraph(RunState)
    graph.add_node("plan", plan)
    graph.add_node("resolve", resolve)
    graph.add_node("gather", gather)
    graph.add_node("specialist", specialist)  # type: ignore[arg-type]
    graph.add_node("verify", check)
    graph.add_node("compose", compose)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", after_plan, ["resolve", END])
    graph.add_conditional_edges("resolve", after_resolve, ["gather", END])
    graph.add_conditional_edges("gather", fan_out, ["specialist"])
    graph.add_edge("specialist", "verify")
    graph.add_edge("verify", "compose")
    graph.add_edge("compose", END)
    return graph.compile()
