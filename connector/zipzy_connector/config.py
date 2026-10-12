"""Settings: environment variables (set by the install command) + connector.yaml (by the customer).

connector.yaml example:

    databases:
      - name: orders-db              # how it is called in ZipZy
        engine: postgres             # postgres | mysql | mariadb
        host: 10.0.1.15
        port: 5432                   # optional, engine default
        database: orders             # required for postgres
        user: zipzy_monitor
        password_env: ORDERS_DB_PASSWORD   # or password_file: /run/secrets/orders, or password: ...
        tls: prefer                  # disable | prefer | require | verify-full
        environment: production      # optional: where it lands in ZipZy the first time
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

# Same rule as the control plane (schemas/datasources.py LOCAL_NAME_RE).
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")

SUPPORTED_ENGINES = ("postgres", "mysql", "mariadb")
PLANNED_ENGINES = ("mongodb", "mssql")
DEFAULT_PORTS = {"postgres": 5432, "mysql": 3306, "mariadb": 3306}


class ConfigError(Exception):
    """connector.yaml or the environment is wrong. The message says how to fix it."""


class DatabaseConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    engine: Literal["postgres", "mysql", "mariadb"]
    host: str = Field(min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=128)
    user: str = Field(min_length=1, max_length=128)
    password: SecretStr | None = None
    password_env: str | None = Field(default=None, max_length=128)
    password_file: Path | None = None
    tls: Literal["disable", "prefer", "require", "verify-full"] = "prefer"
    environment: str | None = Field(default=None, max_length=60)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not NAME_RE.match(v):
            raise ValueError(
                "use letters, digits, '.', '_' or '-' (max 100), starting with a letter or digit"
            )
        return v

    @field_validator("engine", mode="before")
    @classmethod
    def _check_engine(cls, v: object) -> object:
        if isinstance(v, str) and v.lower() in PLANNED_ENGINES:
            raise ValueError(f"'{v}' is not supported by this connector version yet")
        return v.lower() if isinstance(v, str) else v

    @model_validator(mode="after")
    def _check(self) -> Self:
        sources = [
            self.password is not None,
            self.password_env is not None,
            self.password_file is not None,
        ]
        if sum(sources) != 1:
            raise ValueError("give exactly one of: password_env, password_file, password")
        if self.engine == "postgres" and not self.database:
            raise ValueError("'database' is required for postgres")
        return self

    @property
    def effective_port(self) -> int:
        return self.port or DEFAULT_PORTS[self.engine]

    def resolve_password(self) -> str:
        """The password, read at the moment it is needed. Never logged, never sent anywhere."""
        if self.password is not None:
            return self.password.get_secret_value()
        if self.password_env is not None:
            value = os.environ.get(self.password_env)
            if value is None:
                raise ConfigError(
                    f"{self.name}: environment variable {self.password_env} is not set"
                )
            return value
        assert self.password_file is not None  # noqa: S101 - guaranteed by the validator
        try:
            return self.password_file.read_text(encoding="utf-8").rstrip("\n")
        except OSError as exc:
            raise ConfigError(
                f"{self.name}: cannot read password_file {self.password_file}: {exc.strerror}"
            ) from None


class ConnectorFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    databases: list[DatabaseConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_names(self) -> Self:
        seen: set[str] = set()
        for db in self.databases:
            if db.name in seen:
                raise ValueError(f"database name '{db.name}' is used twice")
            seen.add(db.name)
        return self


def load_file(path: Path) -> ConnectorFile:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(f"settings file not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from None
    try:
        return ConnectorFile.model_validate(raw or {})
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'file'}: {e['msg']}" for e in exc.errors()
        )
        raise ConfigError(f"{path}: {problems}") from None


def default_config_path() -> Path:
    return Path(os.environ.get("ZIPZY_CONFIG", "/config/connector.yaml"))


@dataclass(frozen=True, slots=True)
class Settings:
    """From environment variables (the install command sets them)."""

    zipzy_url: str
    enroll_token: str | None
    config_path: Path
    data_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        url = os.environ.get("ZIPZY_URL", "").rstrip("/")
        if not url.startswith(("https://", "http://")):
            raise ConfigError(
                "ZIPZY_URL must be set to the ZipZy address, e.g. https://api.zipzy.in"
            )
        return cls(
            zipzy_url=url,
            enroll_token=os.environ.get("ZIPZY_ENROLL_TOKEN") or None,
            config_path=default_config_path(),
            data_dir=Path(os.environ.get("ZIPZY_DATA_DIR", "/data")),
        )
