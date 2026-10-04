from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"

    database_url: str = Field(
        default="postgresql+asyncpg://zipzy:zipzy@127.0.0.1:5432/zipzy_dba",
        description="SQLAlchemy async URL (postgresql+asyncpg://...)",
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800
    db_echo: bool = False

    # --- Authentication ---------------------------------------------------------------
    # Secret used to sign access tokens (HS256). At least 32 characters, never committed.
    jwt_secret: SecretStr = SecretStr("")
    jwt_issuer: str = "zipzy-dba"
    jwt_audience: str = "zipzy-dba-api"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    # Refresh cookie is Secure (HTTPS only) everywhere except local development.
    cookie_secure: bool = True

    # Development shortcut: trust an X-Dev-User header (email). Refused outside dev/test.
    dev_auth: bool = False

    # Browser origins allowed to call the API (the dashboard), comma-separated.
    cors_origins: str = "http://localhost:3000"

    @model_validator(mode="after")
    def _check_security(self) -> Self:
        if self.dev_auth and self.app_env not in ("development", "test"):
            raise ValueError("DEV_AUTH is only allowed when APP_ENV is development or test")
        if len(self.jwt_secret.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be set and at least 32 characters long")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()