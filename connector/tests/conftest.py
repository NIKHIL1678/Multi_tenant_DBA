"""Shared test settings.

Real databases come from environment variables (CI sets them; locally see README):
  TEST_PG_HOST/PORT/DB, TEST_PG_MONITOR_USER/PASSWORD, TEST_PG_ADMIN_USER/PASSWORD
  TEST_MYSQL_HOST/PORT, TEST_MYSQL_MONITOR_USER/PASSWORD, TEST_MYSQL_ADMIN_USER/PASSWORD
Tests that need a database are skipped when its variables are missing.
"""

import os

import pytest

from zipzy_connector.config import DatabaseConfig


def _env(name: str) -> str | None:
    return os.environ.get(name) or None


def pg_config(user_var: str, password: str | None = None, **extra: object) -> DatabaseConfig:
    if not _env("TEST_PG_HOST"):
        pytest.skip("TEST_PG_* not set")
    return DatabaseConfig.model_validate(
        {
            "name": "pg-test",
            "engine": "postgres",
            "host": _env("TEST_PG_HOST"),
            "port": int(_env("TEST_PG_PORT") or 5432),
            "database": _env("TEST_PG_DB") or "postgres",
            "user": _env(f"TEST_PG_{user_var}_USER"),
            "password": password if password is not None else _env(f"TEST_PG_{user_var}_PASSWORD"),
            "tls": "disable",
            **extra,
        }
    )


def mysql_config(user_var: str, password: str | None = None, **extra: object) -> DatabaseConfig:
    if not _env("TEST_MYSQL_HOST"):
        pytest.skip("TEST_MYSQL_* not set")
    return DatabaseConfig.model_validate(
        {
            "name": "mysql-test",
            "engine": "mysql",
            "host": _env("TEST_MYSQL_HOST"),
            "port": int(_env("TEST_MYSQL_PORT") or 3306),
            "user": _env(f"TEST_MYSQL_{user_var}_USER"),
            "password": password
            if password is not None
            else _env(f"TEST_MYSQL_{user_var}_PASSWORD"),
            "tls": "disable",
            **extra,
        }
    )
