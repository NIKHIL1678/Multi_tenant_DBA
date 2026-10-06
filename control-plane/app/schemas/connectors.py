"""Request and response shapes for connectors."""

import base64
import binascii
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

PUBLIC_KEY_PREFIX = "ed25519:"


def _clean_name(v: str) -> str:
    v = " ".join(v.split())
    if not v:
        raise ValueError("Name cannot be blank")
    return v


class ConnectorCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    _name = field_validator("name")(_clean_name)


class ConnectorUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    _name = field_validator("name")(_clean_name)


class ConnectorOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str  # pending | offline | online | revoked
    version: str | None
    last_seen_at: datetime | None
    datasource_count: int
    # For pending connectors: when the current install command stops working.
    enrollment_expires_at: datetime | None
    created_at: datetime
    revoked_at: datetime | None


class EnrollmentOut(BaseModel):
    # Shown ONCE. Only its hash is stored; issue a new one if it is lost or expires.
    token: str
    expires_at: datetime
    command: str


class ConnectorCreatedOut(BaseModel):
    connector: ConnectorOut
    enrollment: EnrollmentOut


# ---- called by the connector program, not by the dashboard ----------------------------------


class EnrollIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    # The connector's own public key: "ed25519:<base64 of 32 bytes>".
    public_key: str = Field(min_length=20, max_length=200)
    version: str | None = Field(default=None, max_length=30)

    @field_validator("public_key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        if not v.startswith(PUBLIC_KEY_PREFIX):
            raise ValueError("Expected 'ed25519:<base64>'")
        try:
            raw = base64.b64decode(v.removeprefix(PUBLIC_KEY_PREFIX), validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("Public key is not valid base64") from None
        if len(raw) != 32:
            raise ValueError("An Ed25519 public key is exactly 32 bytes")
        return v


class EnrollOut(BaseModel):
    connector_id: uuid.UUID
    tenant_id: uuid.UUID
