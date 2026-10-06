// Permission names, same as the backend catalog (control-plane/app/rbac/catalog.py).
// The UI uses them only to hide what you cannot do; the server still checks every request.

export const Permission = {
  OrgManage: 'org.manage',
  MembersManage: 'members.manage',
  ConnectorsManage: 'connectors.manage',
  DatasourcesManage: 'datasources.manage',
  MetadataRead: 'metadata.read',
  DataRead: 'data.read',
  FindingsRead: 'findings.read',
  ActionsRequest: 'actions.request',
  ActionsApprove: 'actions.approve',
  ActionsExecute: 'actions.execute',
  AuditRead: 'audit.read',
} as const

export type Permission = (typeof Permission)[keyof typeof Permission]

/** Short labels for showing what a role can do. */
export const PERMISSION_LABELS: Record<Permission, string> = {
  'org.manage': 'Company settings',
  'members.manage': 'Manage members',
  'connectors.manage': 'Manage connectors',
  'datasources.manage': 'Manage databases',
  'metadata.read': 'View health & schema',
  'data.read': 'Read row data',
  'findings.read': 'View findings',
  'actions.request': 'Propose changes',
  'actions.approve': 'Approve changes',
  'actions.execute': 'Run changes',
  'audit.read': 'View audit log',
}

/**
 * You may hand out or manage a role only if it has nothing you do not have yourself.
 * Mirrors the backend rule (services/members.py check_can_manage).
 */
export function isWithin(rolePermissions: readonly string[], myPermissions: readonly string[]): boolean {
  return rolePermissions.every((p) => myPermissions.includes(p))
}