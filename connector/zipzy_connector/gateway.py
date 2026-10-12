"""The live link to ZipZy: dial out, prove who we are, then answer allow-listed requests.

Reconnects by itself with growing pauses (1 s up to 60 s, with jitter so a ZipZy restart does
not get every connector back at the same instant). Stops only when ZipZy says the connector is
revoked or its key is not accepted: reconnecting cannot fix those.
"""

import asyncio
import contextlib
import json
import random
import time
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidURI

from zipzy_connector import __version__, log
from zipzy_connector.config import ConnectorFile
from zipzy_connector.engines import probe
from zipzy_connector.identity import Identity
from zipzy_connector.protocol import FINAL_CLOSE_CODES, CloseCode, signed_payload, stream_url
from zipzy_connector.tools import ToolError, run_tool

REPORT_INTERVAL_S = 300  # re-check every database and tell ZipZy
REQUEST_TIMEOUT_S = 60
MAX_PARALLEL_REQUESTS = 4  # never put more than this load on the customer's databases
MIN_BACKOFF_S, MAX_BACKOFF_S = 1.0, 60.0
STABLE_AFTER_S = 60  # a link that lived this long resets the backoff
MAX_MESSAGE_BYTES = 4 * 1024 * 1024


class LinkClosedError(Exception):
    def __init__(self, code: int | None) -> None:
        super().__init__(f"closed with code {code}")
        self.code = code


async def _reports(config: ConnectorFile) -> list[dict[str, Any]]:
    results = await asyncio.gather(*(probe(db) for db in config.databases))
    return [r.report() for r in results]


async def _answer(
    ws: ClientConnection, config: ConnectorFile, msg: dict[str, Any], limit: asyncio.Semaphore
) -> None:
    request_id = str(msg.get("id", ""))[:64]
    tool = str(msg.get("tool", ""))
    raw_args = msg.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    reply: dict[str, Any] = {"type": "response", "id": request_id}
    async with limit:
        try:
            result = await asyncio.wait_for(run_tool(config, tool, args), REQUEST_TIMEOUT_S)
            reply |= {"ok": True, "result": result}
        except ToolError as exc:
            reply |= {"ok": False, "error": {"code": exc.code, "message": exc.message[:500]}}
        except TimeoutError:
            reply |= {"ok": False, "error": {"code": "timeout", "message": "took too long"}}
        except Exception as exc:  # never crash the link because one tool failed
            log.error("tool failed", tool=tool, error=exc.__class__.__name__)
            reply |= {"ok": False, "error": {"code": "tool_failed", "message": "internal error"}}
    log.info("request answered", tool=tool, ok=reply["ok"])
    with contextlib.suppress(ConnectionClosed):
        await ws.send(json.dumps(reply))


async def _report_loop(ws: ClientConnection, config: ConnectorFile) -> None:
    while True:
        await asyncio.sleep(REPORT_INTERVAL_S)
        await ws.send(json.dumps({"type": "report", "databases": await _reports(config)}))


async def session(url: str, identity: Identity, config: ConnectorFile) -> None:
    """One connection, from handshake until it closes. Always ends by raising LinkClosedError."""
    async with connect(
        url,
        open_timeout=15,
        close_timeout=5,
        max_size=MAX_MESSAGE_BYTES,
        ping_interval=None,  # ZipZy sends application pings; we answer them below
        user_agent_header=f"zipzy-connector/{__version__}",
    ) as ws:
        try:
            challenge = json.loads(await asyncio.wait_for(ws.recv(), 15))
            nonce = str(challenge["nonce"])
            await ws.send(
                json.dumps(
                    {
                        "type": "hello",
                        "connector_id": identity.connector_id,
                        "signature": identity.sign(signed_payload(nonce, identity.connector_id)),
                        "version": __version__,
                        "databases": await _reports(config),
                    }
                )
            )
            welcome = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if welcome.get("type") != "welcome":
                raise LinkClosedError(CloseCode.BAD_MESSAGE)
            log.info("connected to ZipZy", databases=len(config.databases))

            limit = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)
            tasks: set[asyncio.Task[None]] = set()
            reporter = asyncio.create_task(_report_loop(ws, config))
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    kind = msg.get("type")
                    if kind == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                    elif kind == "request":
                        task = asyncio.create_task(_answer(ws, config, msg, limit))
                        tasks.add(task)
                        task.add_done_callback(tasks.discard)
            finally:
                reporter.cancel()
                for task in tasks:
                    task.cancel()
        except ConnectionClosed:
            pass
        except (ValueError, KeyError, TimeoutError):
            await ws.close(code=CloseCode.BAD_MESSAGE)
        raise LinkClosedError(ws.close_code)


async def run_forever(zipzy_url: str, identity: Identity, config: ConnectorFile) -> int:
    """Stay connected. Returns an exit code only when reconnecting cannot help."""
    url = stream_url(zipzy_url)
    backoff = MIN_BACKOFF_S
    while True:
        started = time.monotonic()
        try:
            await session(url, identity, config)
        except LinkClosedError as closed:
            if closed.code == CloseCode.REVOKED:
                log.error("this connector was revoked in ZipZy; stopping. Install a new one.")
                return 2
            if closed.code == CloseCode.AUTH_FAILED:
                log.error(
                    "ZipZy did not accept this connector's key; stopping. "
                    "If it was revoked or /data was replaced, install a new connector."
                )
                return 2
            if closed.code in FINAL_CLOSE_CODES:  # pragma: no cover - future final codes
                return 2
            log.warn("link to ZipZy closed; reconnecting", code=closed.code)
        except (OSError, InvalidHandshake, InvalidURI, TimeoutError) as exc:
            log.warn("cannot reach ZipZy; retrying", error=exc.__class__.__name__)

        if time.monotonic() - started >= STABLE_AFTER_S:
            backoff = MIN_BACKOFF_S
        await asyncio.sleep(backoff * random.uniform(0.5, 1.0))  # noqa: S311 - jitter, not crypto
        backoff = min(backoff * 2, MAX_BACKOFF_S)
