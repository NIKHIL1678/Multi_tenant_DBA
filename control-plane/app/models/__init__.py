"""Import every model here so Base.metadata is complete for Alembic autogenerate."""

from app.models.ai import AgentRun, AiConversation, AiMessage, AiUsageDaily, Finding
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.identity import AuthSession, Invitation, Tenant, TenantMember, User
from app.models.infra import Connector, Datasource, EnrollmentToken, Environment, Snapshot
from app.models.rbac import MemberEnvironmentRole, PermissionRow, Role, RolePermission

__all__ = [
    "AgentRun",
    "AiConversation",
    "AiMessage",
    "AiUsageDaily",
    "AuditLog",
    "AuthSession",
    "Base",
    "Connector",
    "Datasource",
    "EnrollmentToken",
    "Environment",
    "Finding",
    "Invitation",
    "MemberEnvironmentRole",
    "PermissionRow",
    "Role",
    "RolePermission",
    "Snapshot",
    "Tenant",
    "TenantMember",
    "User",
]
