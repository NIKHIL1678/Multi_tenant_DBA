import {
  Database,
  History,
  LayoutDashboard,
  Layers,
  PlugZap,
  Settings,
  Sparkles,
  Users,
  type LucideIcon,
} from 'lucide-react'
import { NavLink } from 'react-router'

import { Permission } from '@/lib/permissions'
import { useTenant } from '@/lib/tenant-context'
import { cn } from '@/lib/utils'

type NavItem = { to: string; label: string; icon: LucideIcon; end?: boolean; needs?: Permission }

/** One list for the whole app: the sidebar on desktop and the slide-in menu on phones. */
const NAV_ITEMS: NavItem[] = [
  { to: '', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: 'ai', label: 'AI Assistant', icon: Sparkles, needs: Permission.FindingsRead },
  { to: 'databases', label: 'Databases', icon: Database },
  { to: 'environments', label: 'Environments', icon: Layers },
  { to: 'connectors', label: 'Connectors', icon: PlugZap },
  { to: 'members', label: 'Members', icon: Users },
  { to: 'audit', label: 'Audit log', icon: History, needs: Permission.AuditRead },
  { to: 'settings', label: 'Settings', icon: Settings },
]

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const { tenant, can } = useTenant()

  return (
    <nav aria-label="Company" className="grid gap-0.5 p-3">
      {NAV_ITEMS.filter((item) => !item.needs || can(item.needs)).map(({ to, label, icon: Icon, end }) => (
        <NavLink
          key={label}
          to={to ? `/t/${tenant.id}/${to}` : `/t/${tenant.id}`}
          end={end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none',
              isActive && 'bg-sidebar-accent text-sidebar-accent-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
            )
          }
        >
          <Icon className="size-4 shrink-0" aria-hidden />
          {label}
        </NavLink>
      ))}
    </nav>
  )
}