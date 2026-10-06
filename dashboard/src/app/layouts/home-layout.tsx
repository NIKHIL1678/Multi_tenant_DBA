import { Outlet } from 'react-router'

import { UserMenu } from '@/app/layouts/user-menu'
import { Brand } from '@/components/brand'

/** Pages outside a company (the company list): top bar only, no sidebar. */
export function HomeLayout() {
  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-30 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4 sm:px-6">
          <Brand />
          <UserMenu />
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
        <Outlet />
      </main>
    </div>
  )
}