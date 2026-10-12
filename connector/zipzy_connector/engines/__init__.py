"""One probe per database engine. Adding an engine = one module + one line in PROBES."""

from zipzy_connector.config import DatabaseConfig
from zipzy_connector.engines.base import Prober, ProbeResult
from zipzy_connector.engines.mysql import probe_mysql
from zipzy_connector.engines.postgres import probe_postgres

PROBES: dict[str, Prober] = {
    "postgres": probe_postgres,
    "mysql": probe_mysql,
    "mariadb": probe_mysql,  # same wire protocol; the probe tells them apart by version string
}


async def probe(db: DatabaseConfig) -> ProbeResult:
    return await PROBES[db.engine](db)


__all__ = ["PROBES", "ProbeResult", "probe"]
