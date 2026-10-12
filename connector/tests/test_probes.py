"""Probes against real databases, logged in as the users a customer would create."""

from tests.conftest import mysql_config, pg_config
from zipzy_connector.config import DatabaseConfig
from zipzy_connector.engines import probe


async def test_postgres_monitor_user() -> None:
    r = await probe(pg_config("MONITOR", environment="production"))
    assert r.reachable, r.error
    assert r.engine == "postgres" and r.version and r.version[0].isdigit()
    assert r.capabilities["least_privilege"] is True
    assert r.capabilities["pg_monitor"] is True
    assert r.capabilities["session_read_only"] is True
    assert r.report()["environment"] == "production"


async def test_postgres_superuser_is_flagged() -> None:
    r = await probe(pg_config("ADMIN"))
    assert r.reachable, r.error
    assert r.capabilities["least_privilege"] is False


async def test_postgres_wrong_password_never_leaks_it() -> None:
    r = await probe(pg_config("MONITOR", password="wrong-secret-xyz"))
    assert not r.reachable
    assert r.error and "wrong-secret-xyz" not in r.error


async def test_mysql_monitor_user() -> None:
    r = await probe(mysql_config("MONITOR"))
    assert r.reachable, r.error
    assert r.engine in ("mysql", "mariadb") and r.version
    assert r.capabilities["least_privilege"] is True
    assert r.capabilities["performance_schema"] is True


async def test_mysql_admin_is_flagged() -> None:
    r = await probe(mysql_config("ADMIN"))
    assert r.reachable, r.error
    assert r.capabilities["least_privilege"] is False


async def test_mysql_wrong_password_never_leaks_it() -> None:
    r = await probe(mysql_config("MONITOR", password="wrong-secret-xyz"))
    assert not r.reachable
    assert r.error and "wrong-secret-xyz" not in r.error


async def test_unreachable_host_fails_cleanly() -> None:
    db = DatabaseConfig.model_validate(
        {
            "name": "nowhere",
            "engine": "postgres",
            "host": "127.0.0.1",
            "port": 1,  # nothing listens here
            "database": "x",
            "user": "u",
            "password": "p",
            "tls": "disable",
        }
    )
    r = await probe(db)
    assert not r.reachable and r.error
    assert r.report() == {
        "local_name": "nowhere",
        "engine": "postgres",
        "version": None,
        "reachable": False,
        "capabilities": None,
        "environment": None,
    }


async def test_missing_password_env_is_a_reason_not_a_crash() -> None:
    db = DatabaseConfig.model_validate(
        {
            "name": "x",
            "engine": "mysql",
            "host": "h",
            "user": "u",
            "password_env": "DEFINITELY_NOT_SET_123",
        }
    )
    r = await probe(db)
    assert not r.reachable and r.error and "DEFINITELY_NOT_SET_123" in r.error
