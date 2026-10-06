// The company (tenant) currently open, and what the signed-in user may do in it.
// Provided by the company layout; every page under /t/:tenantId can use it.

import { createContext, useContext } from 'react'

import type { Permission } from '@/lib/permissions'
import type { Tenant } from '@/lib/types'

export type TenantContextValue = {
  tenant: Tenant
  /** True when your company-wide role has this permission. */
  can: (permission: Permission) => boolean
}

export const TenantContext = createContext<TenantContextValue | null>(null)

export function useTenant(): TenantContextValue {
  const ctx = useContext(TenantContext)
  if (!ctx) throw new Error('useTenant must be used inside the company layout')
  return ctx
}