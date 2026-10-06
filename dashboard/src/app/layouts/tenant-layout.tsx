import { Menu } from 'lucide-react'
import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { Outlet, useParams } from 'react-router'

import { CompanySwitcher } from '@/app/layouts/company-switcher'
import { SidebarNav } from '@/app/layouts/sidebar-nav'
import { UserMenu } from '@/app/layouts/user-menu'
import { Brand } from '@/components/brand'
import { QueryError } from '@/components/query-error'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { NotFoundContent } from '@/features/common/not-found-page'
import { useTenantQuery } from '@/features/tenants/api'
import { isNotFound } from '@/lib/api'
import type { Permission } from '@/lib/permissions'
import { TenantContext } from '@/lib/tenant-context'

/**
 * Frame for every page inside a company (/t/:tenantId/...).
 * Desktop: fixed sidebar on the left. Phone/tablet: a menu button opens the same
 * navigation as a slide-in panel.
 */
export function TenantLayout() {
  const { tenantId = '' } = useParams()
  const tenantQuery = useTenantQuery(tenantId)
  const [navOpen, setNavOpen] = useState(false)
  const closeNav = useCallback(() => setNavOpen(false), [])

  const tenant = tenantQuery.data
  const context = useMemo(
    () => (tenant ? { tenant, can: (p: Permission) => tenant.my_permissions.includes(p) } : null),
    [tenant],
  )

  if (tenantQuery.isError) {
    return (
      <Frame>
        <main className="mx-auto w-full max-w-3xl px-4 py-10">
          {isNotFound(tenantQuery.error) ? <NotFoundContent what="Company" /> : <QueryError error={tenantQuery.error} />}
        </main>
      </Frame>
    )
  }

  if (!context) {
    return (
      <Frame>
        <main className="mx-auto w-full max-w-6xl space-y-4 px-4 py-8 sm:px-6">
          <Skeleton className="h-8 w-56" />
          <Skeleton className="h-4 w-80 max-w-full" />
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-28" />
            ))}
          </div>
        </main>
      </Frame>
    )
  }

  return (
    <TenantContext.Provider value={context}>
      <div className="min-h-full md:grid md:grid-cols-[15rem_minmax(0,1fr)]">
        <aside className="sticky top-0 hidden h-screen flex-col border-r bg-sidebar md:flex">
          <div className="flex h-14 items-center border-b px-5">
            <Brand />
          </div>
          <div className="flex-1 overflow-y-auto">
            <SidebarNav />
          </div>
        </aside>

        <div className="flex min-h-full min-w-0 flex-col">
          <header className="sticky top-0 z-30 flex h-14 items-center gap-2 border-b bg-background/85 px-3 backdrop-blur sm:px-4 lg:px-6">
            <Sheet open={navOpen} onOpenChange={setNavOpen}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" className="md:hidden" aria-label="Open navigation">
                  <Menu />
                </Button>
              </SheetTrigger>
              <SheetContent title="Navigation">
                <div className="flex h-14 items-center border-b px-5">
                  <Brand />
                </div>
                <SidebarNav onNavigate={closeNav} />
              </SheetContent>
            </Sheet>
            <CompanySwitcher current={context.tenant} />
            <div className="ml-auto">
              <UserMenu />
            </div>
          </header>
          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
            <Outlet />
          </main>
        </div>
      </div>
    </TenantContext.Provider>
  )
}

/** Top bar without company details, for loading and error states. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-full">
      <header className="flex h-14 items-center justify-between border-b px-4 sm:px-6">
        <Brand />
        <UserMenu />
      </header>
      {children}
    </div>
  )
}