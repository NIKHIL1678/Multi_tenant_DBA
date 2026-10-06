// What the signed-in user may do to other members. The server enforces the same rules;
// here they only decide which buttons to show.

import { useMemo } from 'react'

import { useRoles } from '@/features/members/api'
import { Permission, isWithin } from '@/lib/permissions'
import { useTenant } from '@/lib/tenant-context'
import type { Member, Role } from '@/lib/types'

export type MemberAccess = {
  roles: Role[]
  /** Roles you may hand out: none with more access than your own. */
  assignableRoles: Role[]
  /** True when you may change this member's role, status or environment access. */
  canManage: (member: Member) => boolean
}

/** Owners first, then the most powerful roles, so lists read top-down. */
function byPower(a: Role, b: Role): number {
  return b.permissions.length - a.permissions.length || a.name.localeCompare(b.name)
}

export function useMemberAccess(): MemberAccess & { isLoading: boolean } {
  const { tenant, can } = useTenant()
  const rolesQuery = useRoles(tenant.id)
  const mayManageMembers = can(Permission.MembersManage)

  return useMemo(() => {
    const roles = [...(rolesQuery.data ?? [])].sort(byPower)
    const mine = tenant.my_permissions
    const permissionsOf = new Map(roles.map((r) => [r.id, r.permissions]))
    return {
      isLoading: rolesQuery.isLoading,
      roles,
      assignableRoles: mayManageMembers ? roles.filter((r) => isWithin(r.permissions, mine)) : [],
      canManage: (member) => {
        if (!mayManageMembers) return false
        const target = permissionsOf.get(member.role.id)
        return target !== undefined && isWithin(target, mine)
      },
    }
  }, [rolesQuery.data, rolesQuery.isLoading, tenant.my_permissions, mayManageMembers])
}

/** Badge colour for a role: Owner stands out, everyone else is neutral. */
export function roleBadgeVariant(roleKey: string): 'default' | 'secondary' {
  return roleKey === 'owner' ? 'default' : 'secondary'
}