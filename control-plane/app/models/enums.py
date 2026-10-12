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
    """Read-only questions a connector can answer about a database (connector 0.4.0+)."""

    HEALTH = "health"
    TABLE_STATS = "table_stats"
    INDEXES = "indexes"


class DatasourceStatus(StrEnum):
    UNKNOWN = "unknown"
    CONNECTED = "connected"
    ERROR = "error"


class ActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    CONNECTOR = "connector"
    SYSTEM = "system"
