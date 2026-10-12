"""Which connectors are online right now, and how to ask one of them something.

One ConnectorLink per live WebSocket. The hub sends a request and waits for the matching
response id on THAT link only, so an answer can never cross from one company to another.

Scaling note: the hub lives in this process's memory, so all connector links and all requests
for a connector must reach the same instance. Run the control plane as one instance for now;
going wider means sticky routing or a shared bus (Redis) in front of request().
"""

import asyncio
import contextlib
import secrets
import uuid
from typing import Any

from fastapi import WebSocket

from app.gateway.protocol import ALLOWED_TOOLS, CloseCode


class ConnectorOfflineError(Exception):
    """The connector has no live link to this ZipZy instance."""


class RequestTimeoutError(Exception):
    """The connector did not answer in time."""


class ToolFailedError(Exception):
    """The connector ran the tool and reported an error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ConnectorLink:
    def __init__(self, websocket: WebSocket, connector_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        self.websocket = websocket
        self.connector_id = connector_id
        self.tenant_id = tenant_id
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._send_lock = asyncio.Lock()
        self.closed = False

    async def send(self, message: dict[str, Any]) -> None:
        # Several tasks may send at once (pings, requests): frames must not interleave.
        async with self._send_lock:
            await self.websocket.send_json(message)

    def new_request(self) -> tuple[str, asyncio.Future[dict[str, Any]]]:
        request_id = secrets.token_hex(12)
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        return request_id, future

    def forget(self, request_id: str) -> None:
        self._pending.pop(request_id, None)

    def resolve(self, request_id: str, ok: bool, result: Any, error: Any) -> None:
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return  # late or unknown answer: ignore
        if ok:
            future.set_result(result or {})
        else:
            code = getattr(error, "code", "tool_failed")
            message = getattr(error, "message", "The connector could not run this check.")
            future.set_exception(ToolFailedError(code, message))

    def fail_all(self) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectorOfflineError())
        self._pending.clear()


class ConnectorHub:
    def __init__(self) -> None:
        self._links: dict[uuid.UUID, ConnectorLink] = {}

    def is_online(self, connector_id: uuid.UUID) -> bool:
        return connector_id in self._links

    def online_ids(self) -> set[uuid.UUID]:
        return set(self._links)

    async def attach(self, link: ConnectorLink) -> None:
        """Register a new link. If the same connector was already connected, drop the old link."""
        old = self._links.get(link.connector_id)
        self._links[link.connector_id] = link
        if old is not None and old is not link:
            await self._close(old, CloseCode.REPLACED, "replaced by a newer connection")

    def detach(self, link: ConnectorLink) -> bool:
        """Forget this link. Returns False when a newer link already took its place."""
        link.closed = True
        link.fail_all()
        if self._links.get(link.connector_id) is link:
            del self._links[link.connector_id]
            return True
        return False

    async def disconnect(self, connector_id: uuid.UUID, code: int, reason: str) -> None:
        link = self._links.get(connector_id)
        if link is not None:
            await self._close(link, code, reason)

    async def request(
        self,
        connector_id: uuid.UUID,
        tool: str,
        args: dict[str, Any],
        *,
        wait_seconds: float = 30,
    ) -> dict[str, Any]:
        if tool not in ALLOWED_TOOLS:
            raise ValueError(f"tool {tool!r} is not allowed")  # a programming error, not user input
        link = self._links.get(connector_id)
        if link is None or link.closed:
            raise ConnectorOfflineError
        request_id, future = link.new_request()
        try:
            await link.send({"type": "request", "id": request_id, "tool": tool, "args": args})
            return await asyncio.wait_for(future, timeout=wait_seconds)
        except TimeoutError:
            raise RequestTimeoutError from None
        except (RuntimeError, ConnectionError):
            raise ConnectorOfflineError from None
        finally:
            link.forget(request_id)

    async def _close(self, link: ConnectorLink, code: int, reason: str) -> None:
        self.detach(link)
        with contextlib.suppress(RuntimeError):  # already closed
            await link.websocket.close(code=code, reason=reason)


# One hub per process (see the scaling note above). Endpoints get it through get_hub().
_hub = ConnectorHub()


def get_hub() -> ConnectorHub:
    return _hub
