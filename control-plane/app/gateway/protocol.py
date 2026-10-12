"""Messages between ZipZy and a connector (JSON text frames over one WebSocket).

    ZipZy                                 connector
    ── challenge {nonce} ───────────────►
    ◄────────── hello {connector_id, signature, version, databases}
    ── welcome {heartbeat_seconds} ────►
    ── ping ───────────────────────────►            (every HEARTBEAT_SECONDS)
    ◄──────────────────────────── pong
    ◄──────────────────── report {databases}        (whenever the connector re-checks)
    ── request {id, tool, args} ───────►
    ◄─────────── response {id, ok, result | error}

The connector proves who it is by signing AUTH_CONTEXT + nonce + its id with the private key
created at enrolment; ZipZy checks it with the stored public key. A nonce is used once, so a
recorded handshake cannot be replayed.

The connector package keeps an identical copy of these names (zipzy_connector/protocol.py);
a test on each side pins the wire format.
"""

import base64
import binascii
import uuid
from typing import Annotated, Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.connectors import PUBLIC_KEY_PREFIX
from app.schemas.datasources import ReportedDatasource

PROTOCOL_VERSION = 1
AUTH_CONTEXT = "zipzy-connector-auth-v1"

HANDSHAKE_TIMEOUT_SECONDS = 10
HEARTBEAT_SECONDS = 20
IDLE_TIMEOUT_SECONDS = 60  # no frame at all for this long: the link is dead
MAX_DATABASES = 500

# Tools ZipZy may ask a connector to run. The connector has its own allow-list too; a name has
# to be on BOTH lists to ever run. Every tool is read-only. (Collectors arrive in 4.3.)
ALLOWED_TOOLS = frozenset({"probe"})


class CloseCode:
    """WebSocket close codes (4000-4999 are free for applications)."""

    BAD_MESSAGE = 4400
    AUTH_FAILED = 4401
    REVOKED = 4403
    HANDSHAKE_TIMEOUT = 4408
    REPLACED = 4409  # the same connector connected again; the older link is dropped


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hello(_Msg):
    type: Literal["hello"]
    connector_id: uuid.UUID
    signature: str = Field(min_length=20, max_length=200)
    version: str | None = Field(default=None, max_length=30)
    databases: list[ReportedDatasource] = Field(default_factory=list, max_length=MAX_DATABASES)


class Pong(_Msg):
    type: Literal["pong"]


class Report(_Msg):
    type: Literal["report"]
    databases: list[ReportedDatasource] = Field(max_length=MAX_DATABASES)


class ToolError(_Msg):
    code: str = Field(max_length=50)
    message: str = Field(max_length=500)


class Response(_Msg):
    type: Literal["response"]
    id: str = Field(max_length=64)
    ok: bool
    result: dict[str, Any] | None = None
    error: ToolError | None = None


ConnectorMessage = Annotated[Pong | Report | Response, Field(discriminator="type")]


class Envelope(BaseModel):
    """Parses any message a connector may send after the handshake."""

    message: ConnectorMessage


def signed_payload(nonce: str, connector_id: uuid.UUID | str) -> bytes:
    return f"{AUTH_CONTEXT}\n{nonce}\n{connector_id}".encode()


def verify_signature(public_key: str, nonce: str, connector_id: uuid.UUID, signature: str) -> bool:
    try:
        raw_key = base64.b64decode(public_key.removeprefix(PUBLIC_KEY_PREFIX), validate=True)
        sig = base64.b64decode(signature, validate=True)
        Ed25519PublicKey.from_public_bytes(raw_key).verify(sig, signed_payload(nonce, connector_id))
    except (InvalidSignature, ValueError, binascii.Error):
        return False
    return True
