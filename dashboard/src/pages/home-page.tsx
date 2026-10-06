import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { ErrorAlert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { api, describeError } from '@/lib/api'
import { useAuth, useMe } from '@/lib/auth-context'
import type { Tenant } from '@/lib/types'

/** "Which company?" — lists the companies you belong to and lets you create one. */
export function HomePage() {
  const me = useMe()

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Your companies</h1>
        <p className="mt-1 text-sm text-slate-500">Choose a company to manage its databases.</p>
      </div>

      {me.memberships.length > 0 ? (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {me.memberships.map((m) => (
            <li key={m.tenant_id}>
              <Link
                to={`/t/${m.tenant_id}`}
                className="block rounded-xl border border-slate-200 bg-white p-5 shadow-xs transition hover:border-brand-500 hover:shadow-sm"
              >
                <p className="font-medium text-slate-900">{m.tenant_name}</p>
                <p className="mt-1 text-sm text-slate-500">{m.tenant_slug}</p>
                <span className="mt-3 inline-block rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-medium text-brand-700">
                  {m.role_name}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-600">
          You are not in any company yet. Create one below, or ask your admin for an invitation.
        </p>
      )}

      <CreateCompany />
    </div>
  )
}

function CreateCompany() {
  const { reloadMe } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const tenant = await api<Tenant>('/v1/tenants', { method: 'POST', body: { name: name.trim() } })
      await reloadMe()
      navigate(`/t/${tenant.id}`)
    } catch (err) {
      setError(describeError(err))
      setBusy(false)
    }
  }

  return (
    <Card className="max-w-lg">
      <h2 className="font-medium">Create a company</h2>
      <p className="mt-1 text-sm text-slate-500">
        You become its Owner. We add production, staging and development environments for you.
      </p>
      <form onSubmit={onSubmit} className="mt-4 space-y-3">
        {error && <ErrorAlert>{error}</ErrorAlert>}
        <Input
          label="Company name"
          placeholder="e.g. Sharma Textiles"
          maxLength={150}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <Button type="submit" busy={busy} disabled={!name.trim()}>
          Create company
        </Button>
      </form>
    </Card>
  )
}