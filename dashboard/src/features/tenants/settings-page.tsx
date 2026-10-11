import { Check } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/page-header'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Field } from '@/components/ui/field'
import { useRenameTenant } from '@/features/tenants/api'
import { describeError, fieldErrors } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { formatDate, humanize } from '@/lib/format'
import { Permission, PERMISSION_LABELS } from '@/lib/permissions'
import { useTenant } from '@/lib/tenant-context'

/** Company details (Owners can rename) and what your own role allows here. */
export function SettingsPage() {
  const { tenant, can } = useTenant()
  const isOwner = can(Permission.OrgManage)

  return (
    <>
      <PageHeader title="Settings" description="Company details and your access." />
      <div className="grid max-w-3xl gap-6">
        {isOwner ? <RenameCard key={tenant.name} /> : null}

        <Card>
          <CardHeader>
            <CardTitle>Company</CardTitle>
            <CardDescription>Fixed details used to identify this company.</CardDescription>
          </CardHeader>
          <CardContent>
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-[10rem_minmax(0,1fr)]">
              <Row label="Name">{tenant.name}</Row>
              <Row label="Short name">
                <code className="font-mono">{tenant.slug}</code>
              </Row>
              <Row label="Plan">{humanize(tenant.plan)}</Row>
              <Row label="Status">
                <Badge variant={tenant.status === 'active' ? 'success' : 'warning'}>{humanize(tenant.status)}</Badge>
              </Row>
              <Row label="Created">{formatDate(tenant.created_at)}</Row>
            </dl>
          </CardContent>
        </Card>

        <AccessCard />
      </div>
    </>
  )
}

function RenameCard() {
  const { tenant } = useTenant()
  const { reloadMe } = useAuth()
  const rename = useRenameTenant(tenant.id)
  const [name, setName] = useState(tenant.name)
  const clean = name.trim()
  const errors = fieldErrors(rename.error)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const updated = await rename.mutateAsync(clean).catch(() => null)
    if (!updated) return
    await reloadMe() // the company switcher shows the name too
    toast.success(`Renamed to ${updated.name}`)
  }

  return (
    <Card>
      <form onSubmit={onSubmit}>
        <CardHeader>
          <CardTitle>Company name</CardTitle>
          <CardDescription>Shown to everyone in this company. The short name ({tenant.slug}) does not change.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          {rename.isError && !errors.name && (
            <Alert variant="destructive">
              <AlertDescription>{describeError(rename.error)}</AlertDescription>
            </Alert>
          )}
          <Field label="Name" maxLength={150} value={name} onChange={(e) => setName(e.target.value)} error={errors.name} />
        </CardContent>
        <CardFooter className="justify-end">
          <Button type="submit" busy={rename.isPending} disabled={!clean || clean === tenant.name}>
            Save
          </Button>
        </CardFooter>
      </form>
    </Card>
  )
}

function AccessCard() {
  const { tenant } = useTenant()
  const all = Object.values(Permission)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Your access</CardTitle>
        <CardDescription>
          You are <span className="font-medium text-foreground">{humanize(tenant.my_role_key)}</span> across this company.
          Environment roles can change this inside particular environments.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-2 sm:grid-cols-2">
          {all.map((p) => {
            const has = tenant.my_permissions.includes(p)
            return (
              <li key={p} className={has ? 'flex items-center gap-2 text-sm' : 'flex items-center gap-2 text-sm text-muted-foreground'}>
                <span
                  className={
                    has
                      ? 'grid size-5 place-items-center rounded-full bg-success-soft text-success'
                      : 'grid size-5 place-items-center rounded-full bg-muted'
                  }
                  aria-hidden
                >
                  {has && <Check className="size-3" />}
                </span>
                <span>
                  {PERMISSION_LABELS[p]}
                  <span className="sr-only">{has ? ': allowed' : ': not allowed'}</span>
                </span>
              </li>
            )
          })}
        </ul>
      </CardContent>
    </Card>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate">{children}</dd>
    </>
  )
}