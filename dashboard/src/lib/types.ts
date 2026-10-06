// Friendly names for the API shapes. The shapes themselves are GENERATED from the backend
// (src/types/api.d.ts, via `npm run gen:api`), so they can never drift from the real API.

import type { components } from '@/types/api'

type Schemas = components['schemas']

export type TokenOut = Schemas['TokenOut']
export type Me = Schemas['MeOut']
export type Membership = Schemas['MembershipOut']
export type Tenant = Schemas['TenantOut']
export type TenantOverview = Schemas['TenantOverviewOut']
export type Role = Schemas['RoleOut']
export type RoleRef = Schemas['RoleRef']
export type Member = Schemas['MemberOut']
export type Invitation = Schemas['InvitationOut']
export type InvitationCreated = Schemas['InvitationCreatedOut']
export type Environment = Schemas['EnvironmentOut']
export type Connector = Schemas['ConnectorOut']
export type ConnectorCreated = Schemas['ConnectorCreatedOut']
export type Enrollment = Schemas['EnrollmentOut']
export type Datasource = Schemas['DatasourceOut']