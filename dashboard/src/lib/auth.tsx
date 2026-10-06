// Keeps track of who is signed in. Pages read it with useAuth() / useMe() from auth-context.
//
// On first load we try the refresh cookie: if it works, the user is still signed in
// (e.g. after pressing F5) without typing their password again.

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import { api, refreshAccessToken, setAccessToken, setSessionExpiredHandler } from '@/lib/api'
import { AuthContext, type AuthState } from '@/lib/auth-context'
import type { Me, TokenOut } from '@/lib/types'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' })
  const queryClient = useQueryClient()

  const signOutLocally = useCallback(() => {
    setAccessToken(null)
    queryClient.clear() // never show the previous user's data to the next one
    setState({ status: 'signed-out' })
  }, [queryClient])

  const reloadMe = useCallback(async () => {
    const me = await api<Me>('/v1/me')
    setState({ status: 'signed-in', me })
  }, [])

  useEffect(() => {
    setSessionExpiredHandler(signOutLocally)
    let cancelled = false
    refreshAccessToken()
      .then(async (ok) => {
        if (!ok) throw new Error('no session')
        const me = await api<Me>('/v1/me')
        if (!cancelled) setState({ status: 'signed-in', me })
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'signed-out' })
      })
    return () => {
      cancelled = true
    }
  }, [signOutLocally])

  const login = useCallback(
    async (email: string, password: string) => {
      const token = await api<TokenOut>('/v1/auth/login', {
        method: 'POST',
        body: { email, password },
      })
      setAccessToken(token.access_token)
      await reloadMe()
    },
    [reloadMe],
  )

  const logout = useCallback(async () => {
    try {
      await api<void>('/v1/auth/logout', { method: 'POST' })
    } finally {
      signOutLocally()
    }
  }, [signOutLocally])

  const value = useMemo(() => ({ state, login, logout, reloadMe }), [state, login, logout, reloadMe])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}