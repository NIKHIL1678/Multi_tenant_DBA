import { Layers, MoreHorizontal, ShieldCheck, UserCheck, UserX } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { Member } from '@/lib/types'

export type MemberActionKind = 'role' | 'environments' | 'suspend' | 'reactivate'

/** The "⋯" menu on a member row. */
export function MemberActions({
  member,
  isMe,
  onAction,
}: {
  member: Member
  isMe: boolean
  onAction: (kind: MemberActionKind, member: Member) => void
}) {
  const who = member.full_name ?? member.email
  const suspended = member.status === 'suspended'
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Actions for ${who}`}>
          <MoreHorizontal />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem onSelect={() => onAction('role', member)}>
          <ShieldCheck />
          Change role
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => onAction('environments', member)}>
          <Layers />
          Environment access
        </DropdownMenuItem>
        {!isMe && (
          <>
            <DropdownMenuSeparator />
            {suspended ? (
              <DropdownMenuItem onSelect={() => onAction('reactivate', member)}>
                <UserCheck />
                Reactivate
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem variant="destructive" onSelect={() => onAction('suspend', member)}>
                <UserX />
                Suspend
              </DropdownMenuItem>
            )}
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}