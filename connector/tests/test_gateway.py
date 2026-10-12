"""The connector's live link, against a fake ZipZy that checks signatures like the real one."""

import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from websockets.asyncio.server import ServerConnection, serve

from zipzy_connector import gateway
from zipzy_connector.config import ConnectorFile
from zipzy_connector.identity import Identity
from zipzy_connector.protocol import CloseCode, signed_payload, stream_url

Script = Callable[[ServerConnection], Awaitable[None]]

CONFIG = ConnectorFile.model_validate(
    {
        "databases": [
            {
                "name": "broken",
                "engine": "postgres",
                "host": "127.0.0.1",
                "port": 1,  # nothing listens: the probe reports "unreachable"
                "database": "x",
                "user": "u",
                "password": "s3cret-pass-xyz",
                "tls": "disable",
            }
        ]
    }
)


@pytest.fixture
def identity() -> Identity:
    return Identity(connector_id="c-123", tenant_id="t-1", private_key=Ed25519PrivateKey.generate())


@pytest.fixture(autouse=True)
def fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gateway, "MIN_BACKOFF_S", 0.01)
    monkeypatch.setattr(gateway, "MAX_BACKOFF_S", 0.02)


async def zipzy(identity: Identity, scripts: list[Script]) -> tuple[Any, str, list[dict[str, Any]]]:
    """A fake ZipZy. Each new connection runs the next script after a real handshake check."""
    hellos: list[dict[str, Any]] = []
    public = identity.private_key.public_key()

    async def handler(ws: ServerConnection) -> None:
        nonce = base64.urlsafe_b64encode(b"n" * 32).decode() + str(len(hellos))
        await ws.send(json.dumps({"type": "challenge", "nonce": nonce, "protocol": 1}))
        hello = json.loads(await ws.recv())
        hellos.append(hello)
        verify(public, hello, nonce)
        await ws.send(json.dumps({"type": "welcome", "heartbeat_seconds": 20}))
        await scripts[min(len(hellos), len(scripts)) - 1](ws)

    server = await serve(handler, "127.0.0.1", 0)
    port = next(iter(server.sockets)).getsockname()[1]
    return server, f"http://127.0.0.1:{port}", hellos


def verify(public: Ed25519PublicKey, hello: dict[str, Any], nonce: str) -> None:
    sig = base64.b64decode(hello["signature"])
    public.verify(sig, signed_payload(nonce, hello["connector_id"]))  # raises if wrong


async def ask(ws: ServerConnection, request_id: str, tool: str, args: dict[str, Any]) -> Any:
    await ws.send(json.dumps({"type": "request", "id": request_id, "tool": tool, "args": args}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("type") == "response" and msg["id"] == request_id:
            return msg


# ---- tests ------------------------------------------------------------------------------------


def test_wire_format_matches_the_gateway() -> None:
    assert signed_payload("abc", "c-1") == b"zipzy-connector-auth-v1\nabc\nc-1"
    assert stream_url("https://api.zipzy.in") == "wss://api.zipzy.in/v1/connectors/stream"
    assert stream_url("http://127.0.0.1:8000") == "ws://127.0.0.1:8000/v1/connectors/stream"
    assert (CloseCode.AUTH_FAILED, CloseCode.REVOKED) == (4401, 4403)


async def test_handshake_heartbeat_and_allow_listed_requests(identity: Identity) -> None:
    answers: dict[str, Any] = {}

    async def script(ws: ServerConnection) -> None:
        await ws.send(json.dumps({"type": "ping"}))
        answers["pong"] = json.loads(await ws.recv())
        answers["probe"] = await ask(ws, "r1", "probe", {"datasource": "broken"})
        answers["unknown_tool"] = await ask(ws, "r2", "run_sql", {"sql": "drop table x"})
        answers["unknown_db"] = await ask(ws, "r3", "probe", {"datasource": "not-mine"})
        await ws.close(CloseCode.REVOKED, "revoked")

    server, url, hellos = await zipzy(identity, [script])
    async with server:
        code = await asyncio.wait_for(gateway.run_forever(url, identity, CONFIG), 20)

    assert code == 2, "revoked: the connector stops instead of retrying forever"
    hello = hellos[0]
    assert hello["connector_id"] == "c-123" and hello["version"]
    assert [d["local_name"] for d in hello["databases"]] == ["broken"]
    assert hello["databases"][0]["reachable"] is False
    assert "s3cret-pass-xyz" not in json.dumps(hellos), "passwords never leave the connector"
    assert answers["pong"] == {"type": "pong"}

    probe = answers["probe"]
    assert probe["ok"] is True
    assert probe["result"]["local_name"] == "broken" and probe["result"]["reachable"] is False
    assert probe["result"]["error"]

    assert answers["unknown_tool"]["ok"] is False
    assert answers["unknown_tool"]["error"]["code"] == "unknown_tool"
    assert answers["unknown_db"]["error"]["code"] == "unknown_datasource"


async def test_reconnects_after_a_normal_close(identity: Identity) -> None:
    async def drop(ws: ServerConnection) -> None:
        await ws.close(1001, "server restarting")

    async def revoke(ws: ServerConnection) -> None:
        await ws.close(CloseCode.REVOKED, "revoked")

    server, url, hellos = await zipzy(identity, [drop, drop, revoke])
    async with server:
        code = await asyncio.wait_for(gateway.run_forever(url, identity, CONFIG), 20)
    assert code == 2
    assert len(hellos) == 3, "it came back after each drop, signing a fresh challenge each time"


async def test_rejected_key_stops_with_an_explanation(
    identity: Identity, capsys: pytest.CaptureFixture[str]
) -> None:
    async def reject(ws: ServerConnection) -> None:
        await ws.close(CloseCode.AUTH_FAILED, "authentication failed")

    server, url, _ = await zipzy(identity, [reject])
    async with server:
        code = await asyncio.wait_for(gateway.run_forever(url, identity, CONFIG), 20)
    assert code == 2
    assert "did not accept this connector's key" in capsys.readouterr().out


async def test_unreachable_zipzy_keeps_retrying(identity: Identity) -> None:
    # Nothing listens on port 1: the connector must keep trying, not crash or exit.
    task = asyncio.create_task(gateway.run_forever("http://127.0.0.1:1", identity, CONFIG))
    await asyncio.sleep(0.3)
    assert not task.done()
    task.cancel()
