import { ArrowRightLeft, MoreHorizontal, Trash2 } from 'lucide-react'

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

export type DatasourceActionKind = 'move' | 'remove'

/** The "⋯" menu on a database row. */
export function DatasourceActions({
  datasource: ds,
  isOwner,
  onAction,
}: {
  datasource: Datasource
  isOwner: boolean
  onAction: (kind: DatasourceActionKind, datasource: Datasource) => void
}) {
  const ownerOnly = ds.environment.is_production && !isOwner
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Actions for ${ds.local_name}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
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
      </DropdownMenuContent>
    </DropdownMenu>
  )
}