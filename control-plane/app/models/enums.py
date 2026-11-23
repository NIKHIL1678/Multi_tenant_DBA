from enum import StrEnum


class TenantPlan(StrEnum):
    FREE = "free"
    STARTER = "starter"
    GROWTH = "growth"
    ENTERPRISE = "enterprise"


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class AuthProvider(StrEnum):
    PASSWORD = "password"  # noqa: S105 - enum label, not a secret
    GOOGLE = "google"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class MemberStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class ConnectorStatus(StrEnum):
    PENDING = "pending"
    ONLINE = "online"
    OFFLINE = "offline"
    REVOKED = "revoked"


class DbEngine(StrEnum):
    POSTGRES = "postgres"
    MYSQL = "mysql"
    MARIADB = "mariadb"
    MONGODB = "mongodb"
    MSSQL = "mssql"


class Collector(StrEnum):
    """Read-only questions a connector can answer about a database.

    health, table_stats, indexes: connector 0.4.0+; slow_queries, locks, table_index: 0.6.0+.
    """

    HEALTH = "health"
    TABLE_STATS = "table_stats"
    INDEXES = "indexes"
    SLOW_QUERIES = "slow_queries"
    LOCKS = "locks"
    TABLE_INDEX = "table_index"


class DatasourceStatus(StrEnum):
    UNKNOWN = "unknown"
    CONNECTED = "connected"
    ERROR = "error"


class ActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    CONNECTOR = "connector"
    SYSTEM = "system"
