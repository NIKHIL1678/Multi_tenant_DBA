// Friendly names for the API shapes. The shapes themselves are GENERATED from the backend
// (src/types/api.d.ts, via `npm run gen:api`), so they can never drift from the real API.

import type { components } from '@/types/api'

type Schemas = components['schemas']

export type TokenOut = Schemas['TokenOut']
export type Me = Schemas['MeOut']
export type Membership = Schemas['MembershipOut']
export type Tenant = Schemas['TenantOut']
export type TenantOverview = Schemas['TenantOverviewOut']