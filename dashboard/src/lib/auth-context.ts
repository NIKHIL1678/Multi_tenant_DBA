// The signed-in state shared by every page. The provider lives in auth.tsx.

import { createContext, useContext } from 'react'

import type { Me } from '@/lib/types'

export type AuthState =
  | { status: 'loading' }
  | { status: 'signed-out' }
  | { status: 'signed-in'; me: Me }

export type AuthContextValue = {
  state: AuthState
  login: (email: string, password: string) => Promise<void>
  signup: (input: { email: string; password: string; fullName: string }) => Promise<void>
  logout: () => Promise<void>
  reloadMe: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}

/** For pages that only render when signed in. */
export function useMe(): Me {
  const { state } = useAuth()
  if (state.status !== 'signed-in') throw new Error('useMe used outside a signed-in page')
  return state.me
}