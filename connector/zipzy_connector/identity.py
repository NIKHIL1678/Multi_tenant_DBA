"""Who this connector is, and how it proves it.

On first start the connector creates its own Ed25519 key pair and sends ONLY the public half
to ZipZy together with the one-time enrolment token. The private key never leaves the
/data volume. From then on the connector proves who it is by signing a fresh challenge
(see sign()), so there is no long-lived password or API key to steal from ZipZy's side.
"""

import base64
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

IDENTITY_FILE = "identity.json"
PUBLIC_KEY_PREFIX = "ed25519:"


class EnrollmentError(Exception):
    """Enrolment failed. The message is safe to show and says what to do."""


@dataclass(frozen=True, slots=True)
class Identity:
    connector_id: str
    tenant_id: str
    private_key: Ed25519PrivateKey

    @property
    def public_key(self) -> str:
        raw = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return PUBLIC_KEY_PREFIX + base64.b64encode(raw).decode()

    def sign(self, message: bytes) -> str:
        return base64.b64encode(self.private_key.sign(message)).decode()


def public_key_of(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return PUBLIC_KEY_PREFIX + base64.b64encode(raw).decode()


# ---- storage -----------------------------------------------------------------------------------


def load(data_dir: Path) -> Identity | None:
    path = data_dir / IDENTITY_FILE
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    key = serialization.load_pem_private_key(data["private_key"].encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise EnrollmentError(f"{path} does not hold an Ed25519 key. Delete it and enrol again.")
    return Identity(connector_id=data["connector_id"], tenant_id=data["tenant_id"], private_key=key)


def save(data_dir: Path, identity: Identity) -> None:
    """Write atomically, readable by this user only (the key must not leak to other users)."""
    data_dir.mkdir(parents=True, exist_ok=True)
    pem = identity.private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    payload = json.dumps(
        {
            "connector_id": identity.connector_id,
            "tenant_id": identity.tenant_id,
            "private_key": pem,
        },
        indent=2,
    )
    tmp = data_dir / f".{IDENTITY_FILE}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(payload)
    os.replace(tmp, data_dir / IDENTITY_FILE)


# ---- enrolment ---------------------------------------------------------------------------------


async def enroll(
    client: httpx.AsyncClient, *, zipzy_url: str, token: str, version: str
) -> Identity:
    key = Ed25519PrivateKey.generate()
    try:
        res = await client.post(
            f"{zipzy_url}/v1/connectors/enroll",
            json={"token": token, "public_key": public_key_of(key), "version": version},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise EnrollmentError(f"cannot reach {zipzy_url}: {exc.__class__.__name__}") from None

    if res.status_code == 401:
        raise EnrollmentError(
            "the install command is invalid, expired or already used. "
            "In ZipZy, open the connector's menu and choose 'New install command'."
        )
    if res.status_code != 200:
        raise EnrollmentError(
            f"ZipZy answered {res.status_code} during enrolment; try again shortly"
        )
    body = res.json()
    return Identity(connector_id=body["connector_id"], tenant_id=body["tenant_id"], private_key=key)


async def ensure_enrolled(
    client: httpx.AsyncClient, *, data_dir: Path, zipzy_url: str, token: str | None, version: str
) -> tuple[Identity, bool]:
    """Returns (identity, newly_enrolled). Enrols only once; later starts reuse the saved key."""
    existing = load(data_dir)
    if existing is not None:
        return existing, False
    if not token:
        raise EnrollmentError(
            "not enrolled yet and ZIPZY_ENROLL_TOKEN is not set. "
            "Use the install command from ZipZy."
        )
    identity = await enroll(client, zipzy_url=zipzy_url, token=token, version=version)
    save(data_dir, identity)
    return identity, True
