"""AI agents: conversations, runs, findings and daily usage (docs/08-ai-agents.md).

Every row carries tenant_id and belongs to one datasource; rows go when the datasource goes.
Nothing here holds table rows from a customer database: only statistics, structure,
normalized statement text and what the agents wrote about them.
"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TIMESTAMPTZ, Base, created_at_col, enum_check, updated_at_col, uuid_pk
from app.models.enums import (
    AgentRunKind,
    AgentRunStatus,
    FindingSeverity,
    FindingStatus,
    MessageRole,
)


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)


def _datasource() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("datasources.id", ondelete="CASCADE"), nullable=False
    )


class AiConversation(Base):
    """One person's chat about one datasource.

    `context` remembers what the conversation is about (the table and period chosen), so a
    follow-up such as "add an index to it" needs no new search.
    """

    __tablename__ = "ai_conversations"
    __table_args__ = (Index(None, "datasource_id", "user_id", "updated_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    datasource_id: Mapped[uuid.UUID] = _datasource()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()


class AiMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        Index(None, "conversation_id", "created_at"),
        enum_check("role", MessageRole),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = created_at_col()


class AgentRun(Base):
    """One run of the agent graph: a chat question or an Explain click.

    `steps` is the progress shown while it runs; `clarification` is the question asked when
    the run ends in needs_input; tokens are what Groq reported (both models together).
    """

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index(None, "user_id", "status"),
        Index(None, "datasource_id", "created_at"),
        enum_check("kind", AgentRunKind),
        enum_check("status", AgentRunStatus),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    datasource_id: Mapped[uuid.UUID] = _datasource()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    problem: Mapped[str | None] = mapped_column(Text, nullable=True)  # Explain: problem id
    steps: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_ups: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    clarification: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    notes: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = created_at_col()
    finished_at: Mapped[datetime | None] = mapped_column(TIMESTAMPTZ, nullable=True)


class Finding(Base):
    """A verified finding: every claim cites facts, any SQL passed the allow-list.

    `fingerprint` identifies "the same problem" across runs (category + object), so lists
    can show each problem once. `action` is a suggested statement; running it comes in 5.3.
    """

    __tablename__ = "findings"
    __table_args__ = (
        Index(None, "datasource_id", "status", "created_at"),
        Index(None, "run_id"),
        enum_check("severity", FindingSeverity),
        enum_check("status", FindingStatus),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    datasource_id: Mapped[uuid.UUID] = _datasource()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    specialist: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)  # [{id, summary}]
    table_name: Mapped[str | None] = mapped_column(Text, nullable=True)  # "schema.table"
    action: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=FindingStatus.OPEN)
    created_at: Mapped[datetime] = created_at_col()


class AiUsageDaily(Base):
    """Runs and tokens per company per UTC day, for the daily limits."""

    __tablename__ = "ai_usage_daily"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    runs: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
