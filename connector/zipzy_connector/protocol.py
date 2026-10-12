"""Wire format shared with ZipZy's gateway (control-plane/app/gateway/protocol.py).

Keep the two files in step: tests on both sides pin the signed payload and the close codes.
"""

PROTOCOL_VERSION = 1
AUTH_CONTEXT = "zipzy-connector-auth-v1"
STREAM_PATH = "/v1/connectors/stream"


class CloseCode:
    BAD_MESSAGE = 4400
    AUTH_FAILED = 4401
    REVOKED = 4403
    HANDSHAKE_TIMEOUT = 4408
    REPLACED = 4409


# Close codes after which reconnecting cannot help: stop and tell the operator.
FINAL_CLOSE_CODES = frozenset({CloseCode.AUTH_FAILED, CloseCode.REVOKED})


def signed_payload(nonce: str, connector_id: str) -> bytes:
    return f"{AUTH_CONTEXT}\n{nonce}\n{connector_id}".encode()


def stream_url(zipzy_url: str) -> str:
    """https://api.zipzy.in -> wss://api.zipzy.in/v1/connectors/stream"""
    if zipzy_url.startswith("https://"):
        return "wss://" + zipzy_url.removeprefix("https://") + STREAM_PATH
    return "ws://" + zipzy_url.removeprefix("http://") + STREAM_PATH
