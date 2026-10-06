import { useState } from 'react'
import { Link, Outlet } from 'react-router'

import { Button } from '@/components/ui/button'
import { useAuth, useMe } from '@/lib/auth-context'

export function AppLayout() {
  const me = useMe()
  const { logout } = useAuth()
  const [leaving, setLeaving] = useState(false)

  return (
    <div className="min-h-full">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link to="/" className="flex items-center gap-2 font-semibold text-slate-900">
            <span className="grid size-7 place-items-center rounded-md bg-brand-600 text-xs font-bold text-white">Z</span>
            ZipZy DBA
          </Link>
          <div className="flex items-center gap-3">
            <span className="hidden text-sm text-slate-600 sm:inline">{me.full_name ?? me.email}</span>
            <Button
              variant="ghost"
              busy={leaving}
              onClick={() => {
                setLeaving(true)
                void logout()
              }}
            >
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">
        <Outlet />
      </main>
    </div>
  )
}