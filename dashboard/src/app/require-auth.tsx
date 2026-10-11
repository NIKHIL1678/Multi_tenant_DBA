import { Navigate, Outlet, useLocation } from 'react-router'

import { FullPageSpinner } from '@/components/ui/spinner'
import { useAuth } from '@/lib/auth-context'

/** Wraps every page that needs a signed-in user. */
export function RequireAuth() {
  const { state } = useAuth()
  const location = useLocation()

  if (state.status === 'loading') return <FullPageSpinner />
  if (state.status === 'signed-out') {
    // Remember where they wanted to go; the login page sends them back there.
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search + location.hash }} />
  }
  return <Outlet />
}