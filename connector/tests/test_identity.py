import base64
import json
import stat
import sys
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from zipzy_connector.identity import EnrollmentError, ensure_enrolled, load

URL = "https://zipzy.test"
TOKEN = "zcet_" + "a" * 40


def server(status: int = 200, calls: list[dict[str, object]] | None = None) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL(f"{URL}/v1/connectors/enroll")
        body = json.loads(request.content)
        if calls is not None:
            calls.append(body)
        if status != 200:
            return httpx.Response(status, json={"error": {"code": "x", "message": "x"}})
        return httpx.Response(200, json={"connector_id": "c-1", "tenant_id": "t-1"})

    return httpx.MockTransport(handle)


async def test_enrols_once_and_keeps_the_private_key_local(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    async with httpx.AsyncClient(transport=server(calls=calls)) as client:
        identity, new = await ensure_enrolled(
            client, data_dir=tmp_path, zipzy_url=URL, token=TOKEN, version="0.1.0"
        )
        again, new_again = await ensure_enrolled(
            client, data_dir=tmp_path, zipzy_url=URL, token=TOKEN, version="0.1.0"
        )

    assert (new, new_again) == (True, False)
    assert len(calls) == 1, "the second start must reuse the saved identity"
    assert again.connector_id == identity.connector_id == "c-1"
    assert again.public_key == identity.public_key

    sent = calls[0]
    assert sent["token"] == TOKEN and sent["version"] == "0.1.0"
    assert str(sent["public_key"]).startswith("ed25519:")
    assert "PRIVATE" not in json.dumps(sent)

    path = tmp_path / "identity.json"
    if sys.platform != "win32":  # Windows has no Unix permission bits; the image runs on Linux
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


async def test_signature_verifies_with_the_enrolled_public_key(tmp_path: Path) -> None:
    async with httpx.AsyncClient(transport=server()) as client:
        identity, _ = await ensure_enrolled(
            client, data_dir=tmp_path, zipzy_url=URL, token=TOKEN, version="0.1.0"
        )
    loaded = load(tmp_path)
    assert loaded is not None
    raw = base64.b64decode(identity.public_key.removeprefix("ed25519:"))
    Ed25519PublicKey.from_public_bytes(raw).verify(
        base64.b64decode(loaded.sign(b"nonce")), b"nonce"
    )


async def test_rejected_token_explains_what_to_do(tmp_path: Path) -> None:
    async with httpx.AsyncClient(transport=server(status=401)) as client:
        with pytest.raises(EnrollmentError, match="New install command"):
            await ensure_enrolled(
                client, data_dir=tmp_path, zipzy_url=URL, token=TOKEN, version="0"
            )
    assert load(tmp_path) is None, "nothing is saved when enrolment fails"


async def test_no_token_and_no_identity(tmp_path: Path) -> None:
    async with httpx.AsyncClient(transport=server()) as client:
        with pytest.raises(EnrollmentError, match="ZIPZY_ENROLL_TOKEN"):
            await ensure_enrolled(client, data_dir=tmp_path, zipzy_url=URL, token=None, version="0")


async def test_network_error_is_reported_without_details(tmp_path: Path) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as client:
        with pytest.raises(EnrollmentError, match="cannot reach"):
            await ensure_enrolled(
                client, data_dir=tmp_path, zipzy_url=URL, token=TOKEN, version="0"
            )
