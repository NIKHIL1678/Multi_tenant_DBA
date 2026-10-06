import { Building2, ChevronRight } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { PageHeader } from '@/components/page-header'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { useCreateTenant } from '@/features/tenants/api'
import { describeError, fieldErrors } from '@/lib/api'
import { useAuth, useMe } from '@/lib/auth-context'

/** "Which company?" — the companies you belong to, and creating a new one. */
export function CompaniesPage() {
  const me = useMe()

  return (
    <>
      <PageHeader title="Your companies" description="Choose a company to manage its databases." />

      {me.memberships.length > 0 ? (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {me.memberships.map((m) => (
            <li key={m.tenant_id}>
              <Link
                to={`/t/${m.tenant_id}`}
                className="group flex items-center gap-3 rounded-xl border bg-card p-4 shadow-xs transition-colors hover:border-primary/50 hover:bg-accent/40 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
              >
                <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground">
                  <Building2 className="size-5" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{m.tenant_name}</span>
                  <span className="block truncate text-sm text-muted-foreground">{m.tenant_slug}</span>
                </span>
                <Badge variant="secondary">{m.role_name}</Badge>
                <ChevronRight className="size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">
          You are not in any company yet. Create one below, or ask your admin for an invitation.
        </p>
      )}

      <CreateCompanyCard />
    </>
  )
}

function CreateCompanyCard() {
  const { reloadMe } = useAuth()
  const navigate = useNavigate()
  const create = useCreateTenant()
  const [name, setName] = useState('')

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const tenant = await create.mutateAsync(name.trim()).catch(() => null)
    if (!tenant) return
    await reloadMe()
    toast.success(`${tenant.name} is ready`)
    navigate(`/t/${tenant.id}`)
  }

  const errors = fieldErrors(create.error)
  const generalError = create.isError && Object.keys(errors).length === 0

  return (
    <Card className="mt-8 max-w-xl">
      <CardHeader>
        <CardTitle>Create a company</CardTitle>
        <CardDescription>You become its Owner. We add production, staging and development environments.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="grid gap-4">
          {generalError && (
            <Alert variant="destructive">
              <AlertDescription>{describeError(create.error)}</AlertDescription>
            </Alert>
          )}
          <Field
            label="Company name"
            placeholder="e.g. Sharma Textiles"
            maxLength={150}
            value={name}
            onChange={(e) => setName(e.target.value)}
            error={errors.name}
          />
          <div>
            <Button type="submit" busy={create.isPending} disabled={!name.trim()}>
              Create company
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}