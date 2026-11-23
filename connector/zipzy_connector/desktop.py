"""Desktop start: double-click the connector, answer a few questions, done.

First start
    1. paste the connection code from ZipZy (it holds the ZipZy address + one-time token),
    2. pick MySQL or PostgreSQL and type where it is and the monitoring user's password,
    3. the connector tests the database, registers this computer with ZipZy and connects.
Later starts
    reuse what was saved and connect straight away.

Everything is saved in this user's own folder (APP_DIR): settings, the connector's private key
and the database password. Nothing is sent to ZipZy except health and performance information.
"""

import base64
import binascii
import contextlib
import getpass
import json
import os
import re
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from zipzy_connector import __version__, gateway, identity, log
from zipzy_connector.config import NAME_RE, ConfigError, ConnectorFile, DatabaseConfig, load_file
from zipzy_connector.engines import probe

CODE_PREFIX = "zipzy1."
SETTINGS_FILE = "settings.json"
CONFIG_FILE = "connector.yaml"

MONITOR_SQL = {
    "mysql": (
        "CREATE USER 'zipzy_monitor'@'%' IDENTIFIED BY 'choose-a-password';\n"
        "GRANT PROCESS, REPLICATION CLIENT, SHOW DATABASES, SHOW VIEW ON *.* "
        "TO 'zipzy_monitor'@'%';\n"
        "GRANT SELECT ON performance_schema.* TO 'zipzy_monitor'@'%';"
    ),
    "postgres": (
        "CREATE ROLE zipzy_monitor LOGIN PASSWORD 'choose-a-password';\n"
        "GRANT pg_monitor TO zipzy_monitor;"
    ),
}
ENGINE_NAMES = {"mysql": "MySQL / MariaDB", "postgres": "PostgreSQL"}
DEFAULT_PORTS = {"mysql": 3306, "postgres": 5432}

Ask = Callable[[str], str]


def app_dir() -> Path:
    """%LOCALAPPDATA%\\ZipZyConnector on Windows, ~/.zipzy-connector elsewhere."""
    override = os.environ.get("ZIPZY_DATA_DIR")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "ZipZyConnector"
    return Path.home() / ".zipzy-connector"


# ---- connection code ---------------------------------------------------------------------------


class CodeError(ValueError):
    pass


def encode_code(zipzy_url: str, token: str) -> str:
    """What the dashboard shows (it builds the same thing in the browser)."""
    payload = json.dumps({"u": zipzy_url, "t": token}, separators=(",", ":")).encode()
    return CODE_PREFIX + base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_code(code: str) -> tuple[str, str]:
    code = code.strip()
    if not code.startswith(CODE_PREFIX):
        raise CodeError("that is not a ZipZy connection code (it starts with 'zipzy1.')")
    raw = code[len(CODE_PREFIX) :]
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        url, token = str(data["u"]).rstrip("/"), str(data["t"])
    except (binascii.Error, ValueError, KeyError, TypeError):
        raise CodeError("the code is incomplete; copy it again from ZipZy") from None
    if not url.startswith(("https://", "http://")) or not token.startswith("zcet_"):
        raise CodeError("the code is incomplete; copy it again from ZipZy")
    return url, token


# ---- questions ---------------------------------------------------------------------------------


@dataclass(slots=True)
class Answers:
    engine: str = "mysql"
    host: str = "127.0.0.1"
    port: int = 3306
    database: str = ""
    user: str = "zipzy_monitor"
    password: str = ""


def _ask_default(ask: Ask, question: str, default: str) -> str:
    reply = ask(f"  {question} [{default}]: " if default else f"  {question}: ").strip()
    return reply or default


def _default_name(engine: str) -> str:
    host = re.sub(r"[^A-Za-z0-9_.-]", "-", socket.gethostname().lower()).strip("-.") or "pc"
    name = f"{engine}-{host}"[:100]
    return name if NAME_RE.match(name) else f"{engine}-db"


def ask_database(ask: Ask, ask_secret: Ask, previous: Answers | None = None) -> Answers:
    a = previous or Answers()
    if previous is None:
        print("\nWhich database should ZipZy look after?")
        print("  1) MySQL / MariaDB")
        print("  2) PostgreSQL")
        choice = _ask_default(ask, "Type 1 or 2", "1")
        a.engine = "postgres" if choice.strip() in ("2", "postgres", "postgresql") else "mysql"
        a.port = DEFAULT_PORTS[a.engine]
        a.database = "postgres" if a.engine == "postgres" else ""
        print(
            f"\nZipZy logs in with a read-only monitoring user. If you have not made one yet,"
            f" run this on your {ENGINE_NAMES[a.engine]} as an admin:\n"
        )
        for line in MONITOR_SQL[a.engine].splitlines():
            print(f"    {line}")
        print()
    a.host = _ask_default(ask, "Database host", a.host)
    while True:
        port = _ask_default(ask, "Port", str(a.port))
        if port.isdigit() and 0 < int(port) < 65536:
            a.port = int(port)
            break
        print("  Please type a number such as 3306.")
    if a.engine == "postgres":
        a.database = _ask_default(ask, "Database name", a.database or "postgres")
    a.user = _ask_default(ask, "Monitoring user", a.user)
    while True:
        a.password = ask_secret("  Its password (hidden while you type): ")
        if a.password:
            break
    return a


def _database_config(a: Answers, name: str, **password: Any) -> DatabaseConfig:
    return DatabaseConfig.model_validate(
        {
            "name": name,
            "engine": a.engine,
            "host": a.host,
            "port": a.port,
            "database": a.database or None,
            "user": a.user,
            "tls": "prefer",
            **password,
        }
    )


# ---- saving ------------------------------------------------------------------------------------


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def save_setup(folder: Path, zipzy_url: str, db: DatabaseConfig, password: str) -> None:
    secret = folder / "secrets" / db.name
    _write_private(secret, password)
    entry = db.model_dump(mode="json", exclude_none=True, exclude={"password", "password_env"})
    entry["password_file"] = str(secret)
    _write_private(folder / CONFIG_FILE, yaml.safe_dump({"databases": [entry]}, sort_keys=False))
    _write_private(folder / SETTINGS_FILE, json.dumps({"zipzy_url": zipzy_url}, indent=2))


def load_setup(folder: Path) -> tuple[str, ConnectorFile] | None:
    settings, config = folder / SETTINGS_FILE, folder / CONFIG_FILE
    if not (settings.exists() and config.exists() and (folder / identity.IDENTITY_FILE).exists()):
        return None
    url = str(json.loads(settings.read_text(encoding="utf-8"))["zipzy_url"])
    return url, load_file(config)


# ---- the flow ----------------------------------------------------------------------------------


async def first_time(folder: Path, ask: Ask, ask_secret: Ask) -> tuple[str, ConnectorFile]:
    print("Welcome! This connects one of your databases to ZipZy in about a minute.\n")
    print("In ZipZy, open Connectors > Add connector and copy the connection code.")
    while True:
        try:
            zipzy_url, token = decode_code(ask("  Paste the connection code: "))
            break
        except CodeError as exc:
            print(f"  {exc}.")

    answers: Answers | None = None
    name = ""
    while True:
        answers = ask_database(ask, ask_secret, answers)
        name = name or _default_name(answers.engine)
        db = _database_config(answers, name, password=answers.password)
        print("\n  Testing the database...")
        result = await probe(db)
        if result.reachable:
            count = len(result.catalog["databases"]) if result.catalog else 0
            print(f"  ok  {ENGINE_NAMES[answers.engine]} {result.version}, {count} databases found")
            if result.capabilities.get("least_privilege") is False:
                print("  !!  This user can change data. A read-only monitoring user is safer.")
            break
        print(f"  xx  Could not connect: {result.error}")
        print("  Let's try again (press Enter to keep an answer).\n")

    print("\n  Registering this computer with ZipZy...")
    async with httpx.AsyncClient() as client:
        me = await identity.enroll(client, zipzy_url=zipzy_url, token=token, version=__version__)
    identity.save(folder, me)
    save_setup(folder, zipzy_url, db, answers.password)
    print(f"  ok  Done. Settings are saved in {folder}\n")
    return zipzy_url, load_file(folder / CONFIG_FILE)


async def start(
    folder: Path | None = None, ask: Ask = input, ask_secret: Ask = getpass.getpass
) -> int:
    folder = folder or app_dir()
    log.set_style("pretty")
    print(f"ZipZy DBA connector {__version__}\n")
    try:
        saved = load_setup(folder)
        if saved is None:
            zipzy_url, config = await first_time(folder, ask, ask_secret)
        else:
            zipzy_url, config = saved
            print(f"Already set up (settings in {folder}). Connecting...\n")
        me = identity.load(folder)
        assert me is not None  # noqa: S101 - saved above or checked by load_setup
    except identity.EnrollmentError as exc:
        print(f"\n  xx  {exc}")
        return 2
    except (ConfigError, OSError, ValueError) as exc:
        print(f"\n  xx  {exc}")
        print(f"  To start over, delete the folder {folder} and open the connector again.")
        return 2

    for r in [await probe(db) for db in config.databases]:
        fields = {"database": r.name, "engine": r.engine, "version": r.version}
        if r.reachable:
            log.info("database reachable", **fields)
        else:
            log.warn("database unreachable", **fields, reason=r.error)
    print("Keep this window open: ZipZy can see your database while it runs.\n")
    code = await gateway.run_forever(zipzy_url, me, config)
    if code == 2:
        print(f"\nTo connect again, delete the folder {folder} and open the connector again.")
    return code


def pause_before_exit() -> None:
    """A double-clicked window closes at once; leave the last message readable."""
    if sys.stdin is not None and sys.stdin.isatty():
        with contextlib.suppress(EOFError, KeyboardInterrupt):
            input("\nPress Enter to close.")
