"""What a probe finds out about one database, and the safety rules every engine follows.

A probe:
- connects with the configured (monitoring) user, in a READ-ONLY session,
- learns the version and a few capabilities,
- never reads table rows,
- turns any failure into a short, password-free reason.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from zipzy_connector.config import ConfigError, DatabaseConfig

CONNECT_TIMEOUT_S = 10
PROBE_TIMEOUT_S = 20


@dataclass(slots=True)
class ProbeResult:
    name: str
    engine: str
    reachable: bool
    version: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    # Why it failed, in words safe to show (no passwords, no hostnames beyond the config).
    error: str | None = None
    environment: str | None = None

    def report(self) -> dict[str, Any]:
        """Shape the control plane expects (schemas.datasources.ReportedDatasource)."""
        return {
            "local_name": self.name,
            "engine": self.engine,
            "version": self.version,
            "reachable": self.reachable,
            "capabilities": self.capabilities or None,
            "environment": self.environment,
        }


Prober = Callable[[DatabaseConfig], Awaitable[ProbeResult]]


def failed(db: DatabaseConfig, reason: str) -> ProbeResult:
    return ProbeResult(
        name=db.name, engine=db.engine, reachable=False, error=reason, environment=db.environment
    )


async def guarded(db: DatabaseConfig, run: Callable[[str], Awaitable[ProbeResult]]) -> ProbeResult:
    """Resolve the password, run the engine probe with a hard time limit, never raise."""
    try:
        password = db.resolve_password()
    except ConfigError as exc:
        return failed(db, str(exc))
    try:
        return await asyncio.wait_for(run(password), timeout=PROBE_TIMEOUT_S)
    except TimeoutError:
        return failed(db, f"no answer within {PROBE_TIMEOUT_S}s")
    except Exception as exc:  # any driver error becomes a reported reason
        return failed(db, describe_error(exc, password))


def describe_error(exc: BaseException, password: str) -> str:
    """Driver messages can echo connection details: keep them short, never include the password."""
    text = f"{exc.__class__.__name__}: {exc}".splitlines()[0][:200]
    return text.replace(password, "***") if password else text
