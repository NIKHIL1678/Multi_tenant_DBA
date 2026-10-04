"""Import every model here so Base.metadata is complete for Alembic autogenerate."""

from app.models.audit import AuditLog
from app.models.base import Base
from app.models.identity import Invitation, Tenant, TenantMember, User
from app.models.infra import Connector, Datasource, EnrollmentToken, Environment
from app.models.rbac import MemberEnvironmentRole, PermissionRow, Role, RolePermission

__all__ = [
    "AuditLog",
    "Base",
    "Connector",
    "Datasource",
    "EnrollmentToken",
    "Environment",
    "Invitation",
    "MemberEnvironmentRole",
    "PermissionRow",
    "Role",
    "RolePermission",
    "Tenant",
    "TenantMember",
    "User",
]