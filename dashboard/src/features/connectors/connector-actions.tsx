import { Ban, KeyRound, MoreHorizontal, Pencil } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { Connector } from '@/lib/types'

export type ConnectorActionKind = 'rename' | 'command' | 'revoke'

/** The "⋯" menu on a connector row. Revoked connectors have nothing left to do. */
export function ConnectorActions({
  connector,
  onAction,
}: {
  connector: Connector
  onAction: (kind: ConnectorActionKind, connector: Connector) => void
}) {
  if (connector.status === 'revoked') return null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Actions for ${connector.name}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => onAction('rename', connector)}>
          <Pencil />
          Rename
        </DropdownMenuItem>
        {connector.status === 'pending' && (
          <DropdownMenuItem onSelect={() => onAction('command', connector)}>
            <KeyRound />
            New install command
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem variant="destructive" onSelect={() => onAction('revoke', connector)}>
          <Ban />
          Revoke
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}