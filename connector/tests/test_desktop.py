"""The double-click desktop start: connection code, questions, saving, and the second start."""

import os
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from zipzy_connector import desktop, log
from zipzy_connector.config import DatabaseConfig, load_file
from zipzy_connector.engines.base import ProbeResult
from zipzy_connector.identity import Identity

URL = "https://brave-otter.trycloudflare.com"
TOKEN = "zcet_abc123"


def test_connection_code_round_trip() -> None:
    code = desktop.encode_code(URL, TOKEN)
    assert code.startswith("zipzy1.") and "=" not in code
    assert desktop.decode_code(f"  {code}\n") == (URL, TOKEN)


def test_dashboard_and_connector_agree_on_the_code() -> None:
    # What the dashboard builds in the browser (connection-code.ts) for the same input.
    from_browser = (
        "zipzy1.eyJ1IjoiaHR0cHM6Ly9icmF2ZS1vdHRlci50cnljbG91ZGZsYXJlLmNvbSIsInQi"
        "OiJ6Y2V0X2FiYzEyMyJ9"
    )
    assert desktop.decode_code(from_browser) == (URL, TOKEN)
    assert desktop.encode_code(URL, TOKEN) == from_browser


@pytest.mark.parametrize(
    "bad",
    ["zcet_abc", "zipzy1.!!!", "zipzy1.e30", desktop.encode_code("ftp://x", TOKEN)],
)
def test_bad_codes_are_explained(bad: str) -> None:
    with pytest.raises(desktop.CodeError):
        desktop.decode_code(bad)


def test_default_name_is_a_valid_database_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("zipzy_connector.desktop.socket.gethostname", lambda: "Nikhil's Laptop!")
    assert desktop._default_name("mysql") == "mysql-nikhil-s-laptop"


def test_pretty_log_is_readable(capsys: pytest.CaptureFixture[str]) -> None:
    log.set_style("pretty")
    try:
        log.info("connected to ZipZy", databases=1)
        log.warn("cannot reach ZipZy; retrying", error="OSError")
        log.info("something new", detail="x")
    finally:
        log.set_style("json")
    out = capsys.readouterr().out
    assert "Connected to ZipZy. Your database now appears in the dashboard." in out
    assert "!! Cannot reach ZipZy right now" in out
    assert "something new" in out


class Script:
    """Answers questions in order, like a person typing."""

    def __init__(self, answers: list[str]) -> None:
        self.answers: Iterator[str] = iter(answers)
        self.asked: list[str] = []

    def __call__(self, question: str) -> str:
        self.asked.append(question)
        return next(self.answers)


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    seen: dict[str, Any] = {"probes": [], "enrolled": [], "ran": []}
    passwords_that_work = {"right-pass"}

    async def probe(db: DatabaseConfig) -> ProbeResult:
        seen["probes"].append(db)
        if db.resolve_password() in passwords_that_work:
            return ProbeResult(
                name=db.name,
                engine=db.engine,
                reachable=True,
                version="8.0.43",
                catalog={"databases": [{"name": "zipzy_hrm"}], "truncated": False},
            )
        return ProbeResult(name=db.name, engine=db.engine, reachable=False, error="Access denied")

    async def enroll(client: Any, *, zipzy_url: str, token: str, version: str) -> Identity:
        seen["enrolled"].append((zipzy_url, token))
        return Identity("c-1", "t-1", Ed25519PrivateKey.generate())

    async def run_forever(zipzy_url: str, identity: Identity, config: Any) -> int:
        seen["ran"].append((zipzy_url, identity.connector_id, [d.name for d in config.databases]))
        return 0

    monkeypatch.setattr(desktop, "probe", probe)
    monkeypatch.setattr("zipzy_connector.identity.enroll", enroll)
    monkeypatch.setattr("zipzy_connector.gateway.run_forever", run_forever)
    monkeypatch.setattr("zipzy_connector.desktop.socket.gethostname", lambda: "pc1")
    yield seen
    log.set_style("json")


async def test_first_start_then_second_start(tmp_path: Path, fakes: dict[str, Any]) -> None:
    folder = tmp_path / "ZipZyConnector"
    code = desktop.encode_code(URL, TOKEN)
    ask = Script(["not-a-code", code, "", "", "", ""])  # MySQL with every default
    secret = Script(["wrong-pass", "right-pass"])
    retry = Script(["", "", ""])  # second round: keep host, port, user

    def ask_all(q: str) -> str:
        return ask(q) if len(secret.asked) == 0 else retry(q)

    assert await desktop.start(folder, ask=ask_all, ask_secret=secret) == 0

    assert fakes["enrolled"] == [(URL, TOKEN)], "registered once, with the code's address"
    assert fakes["ran"] == [(URL, "c-1", ["mysql-pc1"])]
    config = load_file(folder / "connector.yaml")
    db = config.databases[0]
    assert (db.engine, db.host, db.port, db.user) == ("mysql", "127.0.0.1", 3306, "zipzy_monitor")
    assert db.password is None and db.password_file is not None
    assert db.resolve_password() == "right-pass"
    assert "right-pass" not in (folder / "connector.yaml").read_text(encoding="utf-8")
    if os.name != "nt":
        for f in ("connector.yaml", "identity.json", "settings.json", "secrets/mysql-pc1"):
            assert stat.S_IMODE((folder / f).stat().st_mode) == 0o600, f

    # Second start: no questions, straight to connecting.
    def no_questions(q: str) -> str:
        raise AssertionError(f"should not ask: {q}")

    fakes["ran"].clear()
    assert await desktop.start(folder, ask=no_questions, ask_secret=no_questions) == 0
    assert fakes["ran"] == [(URL, "c-1", ["mysql-pc1"])]
    assert len(fakes["enrolled"]) == 1


async def test_postgres_asks_for_the_database_name(tmp_path: Path, fakes: dict[str, Any]) -> None:
    ask = Script([desktop.encode_code(URL, TOKEN), "2", "db.local", "", "shop", ""])
    assert await desktop.start(tmp_path, ask=ask, ask_secret=Script(["right-pass"])) == 0
    db = load_file(tmp_path / "connector.yaml").databases[0]
    assert (db.engine, db.host, db.port, db.database) == ("postgres", "db.local", 5432, "shop")


def test_app_dir_follows_the_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZIPZY_DATA_DIR", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", "C:/Users/x/AppData/Local")
    assert desktop.app_dir() == Path("C:/Users/x/AppData/Local") / "ZipZyConnector"
    monkeypatch.setenv("ZIPZY_DATA_DIR", "/data")
    assert desktop.app_dir() == Path("/data")
