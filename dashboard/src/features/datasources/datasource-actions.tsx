import { ArrowRightLeft, Database, MoreHorizontal, RefreshCw, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { Datasource } from '@/lib/types'

export type DatasourceActionKind = 'databases' | 'check' | 'move' | 'remove'

/** The "⋯" menu on a database row. Everyone who sees a server may look and check; managing needs more. */
export function DatasourceActions({
  datasource: ds,
  canManage,
  isOwner,
  onAction,
}: {
  datasource: Datasource
  canManage: boolean
  isOwner: boolean
  onAction: (kind: DatasourceActionKind, datasource: Datasource) => void
}) {
  const ownerOnly = ds.environment.is_production && !isOwner
  const offline = ds.connector.status !== 'online'
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Actions for ${ds.local_name}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <DropdownMenuItem onSelect={() => onAction('databases', ds)}>
          <Database />
          Show databases
        </DropdownMenuItem>
        <DropdownMenuItem disabled={offline} onSelect={() => onAction('check', ds)}>
          <RefreshCw />
          Check now
        </DropdownMenuItem>
        {offline && (
          <DropdownMenuLabel className="font-normal">Its connector is offline, so it cannot be checked now.</DropdownMenuLabel>
        )}
        {canManage && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => onAction('move', ds)}>
              <ArrowRightLeft />
              Move to another environment
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" disabled={ownerOnly} onSelect={() => onAction('remove', ds)}>
              <Trash2 />
              Remove from ZipZy
            </DropdownMenuItem>
            {ownerOnly && (
              <DropdownMenuLabel className="font-normal">Only an Owner can remove a production database.</DropdownMenuLabel>
            )}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
