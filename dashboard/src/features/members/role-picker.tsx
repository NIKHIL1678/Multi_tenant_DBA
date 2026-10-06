import { PERMISSION_LABELS, type Permission } from '@/lib/permissions'
import type { Role } from '@/lib/types'
import { cn } from '@/lib/utils'

/** One line per built-in role, so people choose on meaning rather than on a name. */
const ROLE_SUMMARY: Record<string, string> = {
  owner: 'Full control, including company settings and members.',
  dba: 'Runs the databases: connectors, row data, approving and running changes.',
  it_admin: 'Manages people, connectors and databases. Cannot read row data.',
  backend_dev: 'Reads data and proposes changes for a DBA to review.',
  viewer: 'Sees health and findings only. No row data, no changes.',
}

function permissionList(role: Role): string {
  return role.permissions.map((p) => PERMISSION_LABELS[p as Permission] ?? p).join(', ')
}

/** Choose one role. */
export function RolePicker({
  roles,
  value,
  onChange,
  name,
  disabled,
  labelledBy,
}: {
  roles: Role[]
  value: string
  onChange: (roleId: string) => void
  name: string
  disabled?: boolean
  /** id of the visible label for this group */
  labelledBy?: string
}) {
  return (
    <div role="radiogroup" aria-labelledby={labelledBy} aria-label={labelledBy ? undefined : 'Role'} className="grid gap-2">
      {roles.map((role) => {
        const checked = role.id === value
        return (
          <label
            key={role.id}
            title={permissionList(role)}
            className={cn(
              'flex cursor-pointer gap-3 rounded-lg border px-3 py-2.5 transition-colors',
              'has-focus-visible:ring-[3px] has-focus-visible:ring-ring/50',
              checked ? 'border-primary bg-accent/50' : 'hover:bg-accent/30',
              disabled && 'pointer-events-none opacity-60',
            )}
          >
            <input
              type="radio"
              name={name}
              value={role.id}
              checked={checked}
              onChange={() => onChange(role.id)}
              disabled={disabled}
              className="mt-0.5 size-4 shrink-0 accent-(--color-primary)"
            />
            <span className="min-w-0">
              <span className="block text-sm font-medium">{role.name}</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                {ROLE_SUMMARY[role.key] ?? permissionList(role)}
              </span>
            </span>
          </label>
        )
      })}
    </div>
  )
}