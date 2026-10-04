"""Permission and system-role catalog.

This module is the source of truth the application reads at runtime. The seed migration
(0002) inserts a frozen copy of this data; tests/test_migrations.py asserts that the
database matches this catalog, so any change here must ship with a new migration.
"""

import uuid
from enum import StrEnum


class Permission(StrEnum):
    ORG_MANAGE = "org.manage"
    MEMBERS_MANAGE = "members.manage"
    CONNECTORS_MANAGE = "connectors.manage"
    DATASOURCES_MANAGE = "datasources.manage"
    METADATA_READ = "metadata.read"
    DATA_READ = "data.read"
    FINDINGS_READ = "findings.read"
    ACTIONS_REQUEST = "actions.request"
    ACTIONS_APPROVE = "actions.approve"
    ACTIONS_EXECUTE = "actions.execute"
    AUDIT_READ = "audit.read"


PERMISSION_DESCRIPTIONS: dict[Permission, str] = {
    Permission.ORG_MANAGE: "Manage tenant settings, billing and deletion",
    Permission.MEMBERS_MANAGE: "Invite and remove members, change roles",
    Permission.CONNECTORS_MANAGE: "Create and revoke connectors, issue enrollment tokens",
    Permission.DATASOURCES_MANAGE: "Add and remove datasources, assign environments",
    Permission.METADATA_READ: "View health, schema, indexes and statistics (no row data)",
    Permission.DATA_READ: "Run read queries that return row data",
    Permission.FINDINGS_READ: "View agent findings and recommendations",
    Permission.ACTIONS_REQUEST: "Propose a change to a datasource",
    Permission.ACTIONS_APPROVE: "Approve a proposed change",
    Permission.ACTIONS_EXECUTE: "Execute an approved change",
    Permission.AUDIT_READ: "View the audit log",
}


class SystemRole(StrEnum):
    OWNER = "owner"
    DBA = "dba"
    IT_ADMIN = "it_admin"
    BACKEND_DEV = "backend_dev"
    VIEWER = "viewer"


# Deterministic IDs so system roles are identical in every environment.
_ROLE_NAMESPACE = uuid.UUID("6f1c2d8e-4b7a-5e3f-9a21-7c0d5b8e1f42")


def system_role_id(role: SystemRole) -> uuid.UUID:
    return uuid.uuid5(_ROLE_NAMESPACE, f"system-role:{role.value}")


SYSTEM_ROLE_NAMES: dict[SystemRole, str] = {
    SystemRole.OWNER: "Owner",
    SystemRole.DBA: "DBA",
    SystemRole.IT_ADMIN: "IT Admin",
    SystemRole.BACKEND_DEV: "Backend Developer",
    SystemRole.VIEWER: "Viewer",
}

P = Permission
SYSTEM_ROLE_PERMISSIONS: dict[SystemRole, frozenset[Permission]] = {
    SystemRole.OWNER: frozenset(Permission),
    SystemRole.DBA: frozenset(
        {
            P.CONNECTORS_MANAGE,
            P.DATASOURCES_MANAGE,
            P.METADATA_READ,
            P.DATA_READ,
            P.FINDINGS_READ,
            P.ACTIONS_REQUEST,
            P.ACTIONS_APPROVE,
            P.ACTIONS_EXECUTE,
            P.AUDIT_READ,
        }
    ),
    SystemRole.IT_ADMIN: frozenset(
        {
            P.MEMBERS_MANAGE,
            P.CONNECTORS_MANAGE,
            P.DATASOURCES_MANAGE,
            P.METADATA_READ,
            P.FINDINGS_READ,
            P.AUDIT_READ,
        }
    ),
    SystemRole.BACKEND_DEV: frozenset(
        {P.METADATA_READ, P.DATA_READ, P.FINDINGS_READ, P.ACTIONS_REQUEST}
    ),
    SystemRole.VIEWER: frozenset({P.METADATA_READ, P.FINDINGS_READ}),
}