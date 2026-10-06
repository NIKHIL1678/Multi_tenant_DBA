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