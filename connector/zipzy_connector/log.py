"""Logging in one of two styles.

json    one JSON object per line on stdout: what `docker logs` shows and log collectors
        understand (the default, for servers)
pretty  short sentences for a person watching the window (the desktop `start` command)

Rule: never pass a password, token or private key to these functions.
"""

import json
import sys
from datetime import UTC, datetime
from typing import Any, Literal

Style = Literal["json", "pretty"]
_style: Style = "json"

# What a person watching the window should read, per message.
_FRIENDLY: dict[str, str] = {
    "starting": "Starting the ZipZy connector {version}",
    "identity loaded": "Using this computer's saved connector identity",
    "enrolled": "This computer is now registered with ZipZy",
    "database reachable": "Database {database} reachable ({engine} {version})",
    "database unreachable": "Database {database} is not reachable: {reason}",
    "connected to ZipZy": "Connected to ZipZy. Your database now appears in the dashboard.",
    "cannot reach ZipZy; retrying": "Cannot reach ZipZy right now, trying again...",
    "link to ZipZy closed; reconnecting": "Connection to ZipZy dropped, reconnecting...",
    "request answered": "ZipZy asked for {tool}: answered",
}
_MARK = {"info": "  ok ", "warn": "  !! ", "error": "  xx "}


def set_style(style: Style) -> None:
    global _style
    _style = style


def _say(text: str) -> None:
    try:
        print(text, file=sys.stdout, flush=True)
    except UnicodeEncodeError:  # an old console code page
        print(text.encode("ascii", "replace").decode(), file=sys.stdout, flush=True)


def _emit(level: str, msg: str, **fields: Any) -> None:
    if _style == "pretty":
        template = _FRIENDLY.get(msg)
        try:
            text = template.format(**fields) if template else msg
        except (KeyError, IndexError):
            text = msg
        if template is None and fields.get("detail"):
            text = f"{text}: {fields['detail']}"
        stamp = datetime.now().strftime("%H:%M:%S")
        _say(f"{stamp}{_MARK.get(level, '     ')}{text}")
        return
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
