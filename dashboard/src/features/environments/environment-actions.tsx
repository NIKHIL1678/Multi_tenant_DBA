import { MoreHorizontal, Pencil, ShieldCheck, ShieldOff, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { Environment } from '@/lib/types'

export type EnvironmentActionKind = 'rename' | 'protect' | 'unprotect' | 'delete'

/**
 * The "⋯" menu on an environment row.
 * `isOwner`: may remove production protection and delete production environments.
 */
export function EnvironmentActions({
  environment: env,
  isOwner,
  onAction,
}: {
  environment: Environment
  isOwner: boolean
  onAction: (kind: EnvironmentActionKind, environment: Environment) => void
}) {
  const ownerOnly = env.is_production && !isOwner
  const hasDatabases = env.datasource_count > 0
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Actions for ${env.name}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuItem onSelect={() => onAction('rename', env)}>
          <Pencil />
          Rename
        </DropdownMenuItem>
        {env.is_production ? (
          <DropdownMenuItem disabled={ownerOnly} onSelect={() => onAction('unprotect', env)}>
            <ShieldOff />
            Remove production protection
          </DropdownMenuItem>
        ) : (
          <DropdownMenuItem onSelect={() => onAction('protect', env)}>
            <ShieldCheck />
            Mark as production
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" disabled={ownerOnly || hasDatabases} onSelect={() => onAction('delete', env)}>
          <Trash2 />
          Delete
        </DropdownMenuItem>
        {(ownerOnly || hasDatabases) && (
          <DropdownMenuLabel className="font-normal">
            {hasDatabases
              ? `Move or remove its ${env.datasource_count} database${env.datasource_count === 1 ? '' : 's'} before deleting.`
              : 'Only an Owner can change a production environment’s protection or delete it.'}
          </DropdownMenuLabel>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}