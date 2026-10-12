from pathlib import Path

import pytest

from zipzy_connector.config import ConfigError, Settings, load_file


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "connector.yaml"
    path.write_text(text, encoding="utf-8")
    return path


GOOD = """
databases:
  - name: orders-db
    engine: postgres
    host: 10.0.1.15
    database: orders
    user: zipzy_monitor
    password_env: ORDERS_PW
    environment: production
  - name: inventory
    engine: MySQL
    host: db2.internal
    user: zipzy_monitor
    password_file: /run/secrets/inv
"""


def test_valid_file_with_defaults(tmp_path: Path) -> None:
    cfg = load_file(write(tmp_path, GOOD))
    pg, my = cfg.databases
    assert (pg.effective_port, pg.tls, pg.environment) == (5432, "prefer", "production")
    assert (my.engine, my.effective_port) == ("mysql", 3306)


def test_empty_file_means_no_databases(tmp_path: Path) -> None:
    assert load_file(write(tmp_path, "")).databases == []


@pytest.mark.parametrize(
    ("yaml_text", "expected"),
    [
        (
            "databases:\n  - {name: a, engine: postgres, host: h, database: d, user: u}",
            "exactly one of",
        ),
        (
            "databases:\n  - {name: a, engine: postgres, host: h, database: d, user: u,"
            " password: x, password_env: Y}",
            "exactly one of",
        ),
        ("databases:\n  - {name: a, engine: postgres, host: h, user: u, password: x}", "database"),
        (
            "databases:\n  - {name: a, engine: mongodb, host: h, user: u, password: x}",
            "not supported",
        ),
        (
            "databases:\n  - {name: 'bad name', engine: mysql, host: h, user: u, password: x}",
            "letters",
        ),
        (
            "databases:\n  - {name: a, engine: mysql, host: h, user: u, password: x}\n"
            "  - {name: a, engine: mysql, host: h, user: u, password: x}",
            "used twice",
        ),
        (
            "databases:\n  - {name: a, engine: mysql, host: h, user: u, password: x, colour: red}",
            "colour",
        ),
        ("databases: [\n", "not valid YAML"),
    ],
)
def test_bad_files_say_what_is_wrong(tmp_path: Path, yaml_text: str, expected: str) -> None:
    with pytest.raises(ConfigError, match=expected):
        load_file(write(tmp_path, yaml_text))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_file(tmp_path / "nope.yaml")


def test_password_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = tmp_path / "pw"
    secret.write_text("from-file\n", encoding="utf-8")
    cfg = load_file(
        write(
            tmp_path,
            f"""
databases:
  - {{name: a, engine: mysql, host: h, user: u, password_env: A_PW}}
  - {{name: b, engine: mysql, host: h, user: u, password_file: {secret}}}
  - {{name: c, engine: mysql, host: h, user: u, password: inline}}
""",
        )
    )
    a, b, c = cfg.databases
    with pytest.raises(ConfigError, match="A_PW is not set"):
        a.resolve_password()
    monkeypatch.setenv("A_PW", "from-env")
    assert a.resolve_password() == "from-env"
    assert b.resolve_password() == "from-file"
    assert c.resolve_password() == "inline"
    assert "inline" not in repr(c)  # secrets never show up in logs or tracebacks


def test_settings_need_a_zipzy_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ZIPZY_URL", raising=False)
    with pytest.raises(ConfigError, match="ZIPZY_URL"):
        Settings.from_env()
    monkeypatch.setenv("ZIPZY_URL", "https://api.example.com/")
    monkeypatch.setenv("ZIPZY_ENROLL_TOKEN", "")
    s = Settings.from_env()
    assert s.zipzy_url == "https://api.example.com"
    assert s.enroll_token is None
