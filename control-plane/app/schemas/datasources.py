"""Request and response shapes for datasources (the customer's databases)."""

import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

LOCAL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")


class ConnectorRef(BaseModel):
    id: uuid.UUID
    name: str
    status: str


class EnvironmentRef(BaseModel):
    id: uuid.UUID
    name: str
    is_production: bool


class DatasourceOut(BaseModel):
    id: uuid.UUID
    local_name: str  # the name in the customer's connector.yaml
    engine: str
    version: str | None
    status: str  # unknown | connected | error
    capabilities: dict[str, Any] | None
    last_checked_at: datetime | None
    connector: ConnectorRef
    environment: EnvironmentRef
    created_at: datetime


class DatasourceMoveIn(BaseModel):
    environment_id: uuid.UUID


# ---- reported by a connector (used by the gateway in Phase 4) ---------------------------------


class ReportedDatasource(BaseModel):
    """What a connector says about one database. Never contains passwords or row data."""

    local_name: str = Field(min_length=1, max_length=100)
    # Must list every DbEngine value (a test checks this).
    engine: Literal["postgres", "mysql", "mariadb", "mongodb", "mssql"]
    version: str | None = Field(default=None, max_length=50)
    reachable: bool
    capabilities: dict[str, Any] | None = None
    # Optional hint from connector.yaml; only used the first time the database appears.
    environment: str | None = Field(default=None, max_length=60)

    @field_validator("local_name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not LOCAL_NAME_RE.match(v):
            raise ValueError("Use letters, digits, '.', '_' or '-' (max 100)")
        return v
