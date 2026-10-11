import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Field } from '@/components/ui/field'
import { AuthShell } from '@/features/auth/auth-shell'
import type { AuthLocationState } from '@/features/auth/login-page'
import { ApiError, describeError, fieldErrors } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'

const MIN_PASSWORD = 10 // same rule as the backend

/** Create an account. Afterwards: back to where you came from (e.g. an invitation), else your companies. */
export function SignupPage() {
  const { state, signup } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const nav = location.state as AuthLocationState
  const from = nav?.from ?? '/'

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState(nav?.email ?? '')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  if (state.status === 'signed-in') return <Navigate to={from} replace />

  const tooShort = password.length > 0 && password.length < MIN_PASSWORD
  const errors = fieldErrors(error)
  const emailTaken = error instanceof ApiError && error.status === 409

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (password.length < MIN_PASSWORD) return
    setError(null)
    setBusy(true)
    try {
      await signup({ email: email.trim(), password, fullName: fullName.trim() })
      navigate(from, { replace: true })
    } catch (err) {
      setError(err)
      setBusy(false)
    }
  }

  return (
    <AuthShell
      title="Create your account"
      subtitle="Free to start. No credit card."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" state={nav} className="font-medium text-primary underline-offset-4 hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="grid gap-4" noValidate>
        {error != null && Object.keys(errors).length === 0 && (
          <Alert variant="destructive">
            <AlertDescription>
              {describeError(error)}
              {emailTaken && (
                <>
                  {' '}
                  <Link to="/login" state={{ ...nav, email }} className="font-medium underline underline-offset-4">
                    Sign in instead
                  </Link>
                </>
              )}
            </AlertDescription>
          </Alert>
        )}
        <Field
          label="Your name"
          autoComplete="name"
          required
          maxLength={150}
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          error={errors.full_name}
        />
        <Field
          label="Work email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={errors.email}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          maxLength={128}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={tooShort ? `At least ${MIN_PASSWORD} characters` : errors.password}
          hint={`At least ${MIN_PASSWORD} characters. A short sentence works well.`}
        />
        <Button type="submit" className="w-full" busy={busy} disabled={!fullName.trim() || !email.trim() || password.length < MIN_PASSWORD}>
          Create account
        </Button>
      </form>
    </AuthShell>
  )
}