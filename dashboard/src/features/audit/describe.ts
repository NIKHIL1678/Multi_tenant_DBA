// Turns an audit entry into one readable sentence, e.g.
//   "changed Rahul Gupta's role from Backend Developer to DBA".
// Unknown actions still show (as "member environment role set") so nothing is ever hidden.

import { humanize } from '@/lib/format'
import type { AuditEntry } from '@/lib/types'

export type DescribeContext = {
  /** Role key -> display name ("backend_dev" -> "Backend Developer"). */
  roleName: (key: unknown) => string
  /** Member id -> name or email, for entries that only store the member id. */
  memberName: (memberId: string | null) => string
}

type Details = Record<string, unknown>
type Change = { from?: unknown; to?: unknown }

const str = (v: unknown, fallback = '?'): string => (typeof v === 'string' && v ? v : fallback)
const change = (v: unknown): Change | undefined => (v && typeof v === 'object' ? (v as Change) : undefined)

export function describeEntry(entry: AuditEntry, ctx: DescribeContext): string {
  const d: Details = entry.details ?? {}
  const member = d.email ? str(d.email) : ctx.memberName(entry.target_id)

  switch (entry.action) {
    case 'tenant.created':
      return `created the company ${str(d.name)}`
    case 'tenant.renamed':
      return `renamed the company from ${str(d.from)} to ${str(d.to)}`

    case 'member.role_changed':
      return `changed ${member}’s role from ${ctx.roleName(d.from)} to ${ctx.roleName(d.to)}`
    case 'member.suspended':
      return `suspended ${member}`
    case 'member.reactivated':
      return `reactivated ${member}`
    case 'member.environment_role_set':
      return d.from
        ? `changed ${member}’s role in ${str(d.environment)} from ${ctx.roleName(d.from)} to ${ctx.roleName(d.to)}`
        : `made ${member} ${ctx.roleName(d.to)} in ${str(d.environment)}`
    case 'member.environment_role_removed':
      return `removed ${member}’s ${ctx.roleName(d.from)} role in one environment (company role applies again)`

    case 'invitation.created':
      return `invited ${str(d.email)} as ${ctx.roleName(d.role)}${d.replaced ? ' (replacing an earlier invitation)' : ''}`
    case 'invitation.revoked':
      return `cancelled the invitation for ${str(d.email)}`
    case 'invitation.accepted':
      return `joined as ${ctx.roleName(d.role)} (accepted an invitation)`

    case 'environment.created':
      return `created the ${d.is_production ? 'production ' : ''}environment ${str(d.name)}`
    case 'environment.deleted':
      return `deleted the environment ${str(d.name)}`
    case 'environment.updated': {
      const parts: string[] = []
      const name = change(d.name)
      const prod = change(d.is_production)
      if (name) parts.push(`renamed environment ${str(name.from)} to ${str(name.to)}`)
      if (prod) parts.push(prod.to ? 'marked it as production' : 'removed its production protection')
      return parts.join(' and ') || 'updated an environment'
    }

    case 'connector.created':
      return `added the connector ${str(d.name)}`
    case 'connector.token_issued':
      return `created a new install command for ${str(d.name)}`
    case 'connector.renamed':
      return `renamed connector ${str(d.from)} to ${str(d.to)}`
    case 'connector.revoked':
      return `revoked the connector ${str(d.name)}`
    case 'connector.enrolled':
      return `was installed${d.version ? ` (version ${str(d.version)})` : ''}`

    case 'datasource.discovered':
      return `reported a new database, ${str(d.name)}`
    case 'datasource.moved':
      return `moved the database ${str(d.name)} from ${str(d.from)} to ${str(d.to)}`
    case 'datasource.deleted':
      return `removed the database ${str(d.name)} from ${str(d.environment)}`

    default:
      return humanize(entry.action.replaceAll('.', ' '))
  }
}

/** Who did it, as a short name. */
export function actorName(entry: AuditEntry): string {
  const a = entry.actor
  switch (a.type) {
    case 'user':
      return a.name ?? a.email ?? 'A removed user'
    case 'connector':
      return a.name ? `Connector ${a.name}` : 'A connector'
    case 'agent':
      return a.name ?? 'ZipZy agent'
    default:
      return 'ZipZy'
  }
}

/** The filter "areas": action prefixes the API understands. */
export const AUDIT_AREAS: { value: string; label: string }[] = [
  { value: 'member.', label: 'Members & roles' },
  { value: 'invitation.', label: 'Invitations' },
  { value: 'environment.', label: 'Environments' },
  { value: 'connector.', label: 'Connectors' },
  { value: 'datasource.', label: 'Databases' },
  { value: 'tenant.', label: 'Company' },
]