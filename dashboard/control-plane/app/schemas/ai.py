"""API shapes for the AI agents (Ask AI, Explain)."""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.models.enums import AgentRunKind, AgentRunStatus, MessageRole

ProblemId = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[a-z]+$")]


class RunIn(BaseModel):
    """chat: `message` (and `conversation_id` to continue one), or `table` to answer
    "Which table do you mean?" in that conversation. explain: `problem` (+ its title)."""

    kind: AgentRunKind
    message: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    conversation_id: uuid.UUID | None = None
    table: Annotated[str, Field(min_length=3, max_length=400)] | None = None
    problem: ProblemId | None = None
    problem_title: Annotated[str, Field(min_length=1, max_length=300)] | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        if self.kind == AgentRunKind.EXPLAIN:
            if self.problem is None or self.message or self.table or self.conversation_id:
                raise ValueError("explain takes `problem` (and `problem_title`) only")
        elif (self.message is None) == (self.table is None):
            raise ValueError("chat takes either `message` or `table`")
        elif self.table is not None and self.conversation_id is None:
            raise ValueError("`table` answers a question in a conversation: send its id")
        return self


class Step(BaseModel):
    key: str
    label: str


class EvidenceOut(BaseModel):
    id: str
    summary: str


class ActionOut(BaseModel):
    kind: str
    statement: str
    table: str | None
    reason: str
    risk: Literal["low", "medium", "high"]


class FindingOut(BaseModel):
    id: uuid.UUID
    specialist: str
    severity: Literal["high", "medium", "low"]
    category: str
    title: str
    explanation: str
    evidence: list[EvidenceOut]
    table: str | None
    action: ActionOut | None


class ClarifyOption(BaseModel):
    label: str
    table: str


class Clarification(BaseModel):
    question: str
    options: list[ClarifyOption]


class RunOut(BaseModel):
    id: uuid.UUID
    datasource_id: uuid.UUID
    conversation_id: uuid.UUID | None
    kind: AgentRunKind
    status: AgentRunStatus
    question: str
    steps: list[Step]
    answer: str | None
    follow_ups: list[str]
    clarification: Clarification | None
    notes: list[str]
    error: str | None
    findings: list[FindingOut]
    created_at: datetime
    finished_at: datetime | None


class MessageOut(BaseModel):
    id: uuid.UUID
    role: MessageRole
    content: str
    run_id: uuid.UUID | None
    created_at: datetime


class ConversationOut(BaseModel):
    id: uuid.UUID
    datasource_id: uuid.UUID
    title: str
    context: dict[str, str]
    updated_at: datetime


class ConversationListItem(ConversationOut):
    """A conversation in the AI Assistant list, with the server it is about."""

    datasource_name: str
    engine: str
    environment_name: str
    is_production: bool


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]
    runs: list[RunOut]  # the runs of this conversation, oldest first (answers, findings)


class AiStatusOut(BaseModel):
    enabled: bool  # False: GROQ_API_KEY is not set on the server
    model: str
    runs_today: int
    runs_limit: int
    tokens_today: int
    tokens_limit: int
