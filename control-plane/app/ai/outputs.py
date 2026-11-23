"""What each model call must return. Sent to Groq as strict JSON schemas (strict.py) and
validated again here, with limits, when the answer comes back.

`extra="forbid"` everywhere: an answer with unexpected fields is rejected, not trusted.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import FindingSeverity, Specialist

Short = Annotated[str, Field(min_length=1, max_length=200)]
Text = Annotated[str, Field(min_length=1, max_length=2000)]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Category(StrEnum):
    MISSING_INDEX = "missing_index"
    DUPLICATE_INDEX = "duplicate_index"
    UNUSED_INDEX = "unused_index"
    INVALID_INDEX = "invalid_index"
    NO_PRIMARY_KEY = "no_primary_key"
    FULL_SCANS = "full_scans"
    SLOW_QUERY = "slow_query"
    LOCK_WAIT = "lock_wait"
    LONG_TRANSACTION = "long_transaction"
    CONNECTIONS = "connections"
    CACHE = "cache"
    REPLICATION = "replication"
    BLOAT = "bloat"
    CONFIGURATION = "configuration"
    OTHER = "other"


class PlanOut(_Out):
    """The orchestrator's plan for a chat question."""

    about_this_database: bool  # false: not about this server's health, performance or schema
    asks_for_row_data: bool  # wants rows/values from tables (not available: statistics only)
    specialists: Annotated[list[Specialist], Field(max_length=3)]
    table: Annotated[str, Field(max_length=200)] | None  # words naming a table, or null
    period: Annotated[str, Field(max_length=20)] | None  # "2026-11" or "2026"; code checks it


class ActionOut(_Out):
    statement: Annotated[str, Field(min_length=1, max_length=1000)]
    reason: Short
    risk: Literal["low", "medium", "high"]


class FindingOut(_Out):
    severity: FindingSeverity
    category: Category
    title: Short
    explanation: Text
    evidence: Annotated[list[Annotated[str, Field(max_length=10)]], Field(max_length=12)]
    table: Annotated[str, Field(max_length=200)] | None  # "schema.table" it is about, or null
    action: ActionOut | None


class SpecialistOut(_Out):
    findings: Annotated[list[FindingOut], Field(max_length=8)]
    summary: Text  # what this specialist concluded, for the orchestrator


class AnswerOut(_Out):
    answer: Annotated[str, Field(min_length=1, max_length=4000)]
    follow_ups: Annotated[list[Short], Field(max_length=3)]
