"""Request and response shapes for environments."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

ENV_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")


def _clean_name(v: str) -> str:
    v = v.strip().lower()
    if not ENV_NAME_RE.match(v):
        raise ValueError("Use 1-60 lowercase letters, digits, '-' or '_' (e.g. 'staging-eu')")
    return v


class EnvironmentCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    is_production: bool = False

    _name = field_validator("name")(_clean_name)


class EnvironmentUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    is_production: bool | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        return None if v is None else _clean_name(v)

    @model_validator(mode="after")
    def _something_to_change(self) -> "EnvironmentUpdateIn":
        if self.name is None and self.is_production is None:
            raise ValueError("Send name and/or is_production")
        return self


class EnvironmentOut(BaseModel):
    id: uuid.UUID
    name: str
    is_production: bool
    datasource_count: int
    created_at: datetime
