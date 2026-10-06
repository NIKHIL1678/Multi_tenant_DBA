"""Cursor pagination, shared by every long list (audit log first).

Why cursors and not page numbers: the audit log only grows. With "page 3" a new row pushes
everything down and the reader sees duplicates; with "everything older than X" they never do,
and the database can jump straight to X using an index instead of counting skipped rows.

The cursor is opaque to the dashboard: it just sends back the `next_cursor` it was given.
"""

import base64
import binascii
from datetime import datetime

from pydantic import BaseModel

from app.api.errors import ApiError

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None  # None = this is the last page


def encode_cursor(created_at: datetime, row_id: int) -> str:
    raw = f"{created_at.isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        text = base64.urlsafe_b64decode(padded.encode()).decode()
        stamp, row_id = text.split("|", 1)
        return datetime.fromisoformat(stamp), int(row_id)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise ApiError(422, "invalid_cursor", "This page link is invalid. Start again.") from None
