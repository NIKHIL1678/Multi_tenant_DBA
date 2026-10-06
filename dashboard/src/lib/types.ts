// Shapes returned by the control-plane API (see control-plane/app/schemas/).
// Later these will be generated automatically from /openapi.json.

export type TokenOut = {
  access_token: string
  token_type: 'bearer'
  expires_in: number
}

export type Membership = {
  tenant_id: string
  tenant_name: string
  tenant_slug: string
  role_key: string
  role_name: string
}

export type Me = {
  id: string
  email: string
  full_name: string | null
  memberships: Membership[]
}

export type Tenant = {
  id: string
  name: string
  slug: string
  plan: string
  status: string
  created_at: string
  my_role_key: string
  my_permissions: string[]
}

export type TenantOverview = {
  tenant_id: string
  environments: number
  members: number
  connectors_by_status: Record<string, number>
  datasources_by_engine: Record<string, number>
}