import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { AuthShell } from '@/features/auth/auth-shell'
import { describeError } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'

export type AuthLocationState = { from?: string; email?: string } | null

export function LoginPage() {
  const { state, login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const nav = location.state as AuthLocationState
  const from = nav?.from ?? '/'

  const [email, setEmail] = useState(nav?.email ?? '')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (state.status === 'signed-in') return <Navigate to={from} replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(email.trim(), password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(describeError(err))
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title="Sign in to ZipZy DBA"
      subtitle="Your databases, looked after."
      footer={
        <>
          New here?{' '}
          <Link to="/signup" state={nav} className="font-medium text-primary underline-offset-4 hover:underline">
            Create an account
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="grid gap-4" noValidate>
        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <Field label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Button type="submit" className="w-full" busy={busy} disabled={!email || !password}>
          Sign in
        </Button>
      </form>
    </AuthShell>
  )
}