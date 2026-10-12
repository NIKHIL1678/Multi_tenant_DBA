"""WebSocket endpoint the connectors dial out to.

WS /v1/connectors/stream
    No user is involved: the connector proves who it is by signing a one-time challenge with
    the private key it created at enrolment (see gateway/protocol.py).
"""

import asyncio
import contextlib
import json
import logging
import secrets
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.core.db import SessionFactory, get_session_factory
from app.core.logging import tenant_id_var
from app.gateway import service
from app.gateway.hub import ConnectorHub, ConnectorLink, get_hub
from app.gateway.protocol import (
    HANDSHAKE_TIMEOUT_SECONDS,
    HEARTBEAT_SECONDS,
    IDLE_TIMEOUT_SECONDS,
    PROTOCOL_VERSION,
    CloseCode,
    Envelope,
    Hello,
    Pong,
    Report,
    Response,
    verify_signature,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["gateway"])

Sessions = Annotated[SessionFactory, Depends(get_session_factory)]
Hub = Annotated[ConnectorHub, Depends(get_hub)]

_LINK_ERRORS = (WebSocketDisconnect, RuntimeError, ConnectionError)


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    with contextlib.suppress(RuntimeError):
        await websocket.close(code=code, reason=reason)


async def _receive(websocket: WebSocket, wait_seconds: float) -> Any:
    """Next JSON frame, or raise TimeoutError / ValueError (not JSON) / a link error."""
    text = await asyncio.wait_for(websocket.receive_text(), timeout=wait_seconds)
    return json.loads(text)


@router.websocket("/v1/connectors/stream")
async def connector_stream(websocket: WebSocket, sessions: Sessions, hub: Hub) -> None:
    await websocket.accept()

    # ---- handshake: prove you are who you say -------------------------------------------------
    nonce = secrets.token_urlsafe(32)
    try:
        await websocket.send_json(
            {"type": "challenge", "nonce": nonce, "protocol": PROTOCOL_VERSION}
        )
        raw = await _receive(websocket, HANDSHAKE_TIMEOUT_SECONDS)
    except TimeoutError:
        await _close(websocket, CloseCode.HANDSHAKE_TIMEOUT, "no hello in time")
        return
    except ValueError:
        await _close(websocket, CloseCode.BAD_MESSAGE, "expected JSON")
        return
    except _LINK_ERRORS:
        return

    try:
        hello = Hello.model_validate(raw)
    except ValidationError:
        await _close(websocket, CloseCode.BAD_MESSAGE, "expected hello")
        return

    async with sessions() as session:
        try:
            connector = await service.load_for_handshake(session, hello.connector_id)
        except service.ConnectorRejectedError:
            connector = None
        public_key = connector.public_key if connector else None
        tenant_id = connector.tenant_id if connector else None

    if (
        public_key is None
        or tenant_id is None
        or not verify_signature(public_key, nonce, hello.connector_id, hello.signature)
    ):
        # One answer for every failure: an attacker learns nothing about which ids exist.
        logger.warning(
            "connector handshake rejected", extra={"connector_id": str(hello.connector_id)}
        )
        await _close(websocket, CloseCode.AUTH_FAILED, "authentication failed")
        return

    tenant_id_var.set(str(tenant_id))
    async with sessions() as session:
        try:
            await service.mark_online(
                session, hello.connector_id, version=hello.version, databases=hello.databases
            )
        except service.ConnectorRejectedError:  # revoked between the two steps
            await _close(websocket, CloseCode.REVOKED, "revoked")
            return

    link = ConnectorLink(websocket, hello.connector_id, tenant_id)
    await hub.attach(link)
    logger.info(
        "connector online",
        extra={"connector_id": str(hello.connector_id), "databases": len(hello.databases)},
    )

    # ---- live link ---------------------------------------------------------------------------
    heartbeat = asyncio.create_task(_heartbeat(link))
    try:
        await link.send({"type": "welcome", "heartbeat_seconds": HEARTBEAT_SECONDS})
        await _read_loop(link, sessions)
    except _LINK_ERRORS:
        pass
    finally:
        heartbeat.cancel()
        if hub.detach(link):  # False when a newer link replaced this one: it stays online
            async with sessions() as session:
                await service.mark_offline(session, link.connector_id)
            logger.info("connector offline", extra={"connector_id": str(link.connector_id)})


async def _heartbeat(link: ConnectorLink) -> None:
    with contextlib.suppress(*_LINK_ERRORS, asyncio.CancelledError):
        while not link.closed:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await link.send({"type": "ping"})


async def _read_loop(link: ConnectorLink, sessions: SessionFactory) -> None:
    last_touch = time.monotonic()
    while not link.closed:
        try:
            raw = await _receive(link.websocket, IDLE_TIMEOUT_SECONDS)
        except TimeoutError:
            await _close(link.websocket, CloseCode.HANDSHAKE_TIMEOUT, "idle")
            return
        except ValueError:
            await _close(link.websocket, CloseCode.BAD_MESSAGE, "expected JSON")
            return

        try:
            message = Envelope.model_validate({"message": raw}).message
        except ValidationError:
            await _close(link.websocket, CloseCode.BAD_MESSAGE, "unknown message")
            return

        if isinstance(message, Response):
            link.resolve(message.id, message.ok, message.result, message.error)
        elif isinstance(message, Report):
            async with sessions() as session:
                await service.apply_report(session, link.connector_id, message.databases)
            last_touch = time.monotonic()
        elif (
            isinstance(message, Pong)
            and time.monotonic() - last_touch >= service.LAST_SEEN_EVERY.total_seconds()
        ):
            async with sessions() as session:
                await service.touch(session, link.connector_id)
            last_touch = time.monotonic()
