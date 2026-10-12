"""One JSON object per line on stdout: what `docker logs` shows and log collectors understand.

Rule: never pass a password, token or private key to these functions.
"""

import json
import sys
from datetime import UTC, datetime
from typing import Any


def _emit(level: str, msg: str, **fields: Any) -> None:
    record = {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "level": level,
        "msg": msg,
        **fields,
    }
    print(json.dumps(record, default=str), file=sys.stdout, flush=True)


def info(msg: str, **fields: Any) -> None:
    _emit("info", msg, **fields)


def warn(msg: str, **fields: Any) -> None:
    _emit("warn", msg, **fields)


def error(msg: str, **fields: Any) -> None:
    _emit("error", msg, **fields)
