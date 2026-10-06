import { Building2, Check, ChevronsUpDown, LayoutGrid } from 'lucide-react'
import { useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useMe } from '@/lib/auth-context'
import type { Tenant } from '@/lib/types'

/** Switch between the companies you belong to (top bar). */
export function CompanySwitcher({ current }: { current: Tenant }) {
  const me = useMe()
  const navigate = useNavigate()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" className="h-9 min-w-0 max-w-[60vw] justify-start gap-2 px-2.5 sm:max-w-72">
          <Building2 className="text-muted-foreground" aria-hidden />
          <span className="truncate">{current.name}</span>
          <ChevronsUpDown className="ml-auto text-muted-foreground" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuLabel>Your companies</DropdownMenuLabel>
        {me.memberships.map((m) => (
          <DropdownMenuItem key={m.tenant_id} onSelect={() => navigate(`/t/${m.tenant_id}`)}>
            <span className="min-w-0 flex-1">
              <span className="block truncate">{m.tenant_name}</span>
              <span className="block truncate text-xs text-muted-foreground">{m.role_name}</span>
            </span>
            {m.tenant_id === current.id && <Check className="text-primary!" aria-label="Current" />}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate('/')}>
          <LayoutGrid aria-hidden /> All companies
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}