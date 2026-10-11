import { useMutation, useQuery } from '@tanstack/react-query'
import { Building2, MailWarning } from 'lucide-react'
import { Link, useLocation, useNavigate } from 'react-router'
import { toast } from 'sonner'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { AuthShell } from '@/features/auth/auth-shell'
import { ApiError, api, describeError } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { formatDateTime } from '@/lib/format'
import type { InvitationAccepted, InvitationPreview } from '@/lib/types'

/**
 * /invite#<token> — the link from an invitation.
 * The token sits after '#', which browsers never send to any server, and we pass it to the
 * API in a request body, so it stays out of every access log.
 */
export function InvitePage() {
  const location = useLocation()
  const token = location.hash.replace(/^#/, '')
  const here = `/invite${location.hash}`

  const preview = useQuery({
    queryKey: ['invitation-preview', token],
    queryFn: () => api<InvitationPreview>('/v1/invitations/preview', { method: 'POST', body: { token } }),
    enabled: token.length >= 20,
    retry: false,
  })

  if (token.length < 20 || preview.isError) {
    const notFound = !(preview.error instanceof ApiError) || preview.error.status === 404 || token.length < 20
    return (
      <AuthShell title="This invitation can’t be used" footer={<HomeLink />}>
        <div className="grid gap-3 text-center">
          <MailWarning className="mx-auto size-8 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">
            {notFound
              ? 'The link is invalid, has expired, or was already used. Ask the person who invited you for a new one.'
              : describeError(preview.error)}
          </p>
        </div>
      </AuthShell>
    )
  }

  if (preview.isLoading || !preview.data) {
    return (
      <AuthShell title="Opening your invitation…">
        <div className="grid gap-3" aria-busy>
          <Skeleton className="h-5 w-3/4" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      </AuthShell>
    )
  }

  return <InvitationCard token={token} here={here} invitation={preview.data} />
}

function InvitationCard({ token, here, invitation: inv }: { token: string; here: string; invitation: InvitationPreview }) {
  const { state, logout, reloadMe } = useAuth()
  const navigate = useNavigate()

  const accept = useMutation({
    mutationFn: () => api<InvitationAccepted>('/v1/invitations/accept', { method: 'POST', body: { token } }),
    onSuccess: async (result) => {
      await reloadMe()
      toast.success(`Welcome to ${result.tenant_name}`)
      navigate(`/t/${result.tenant_id}`, { replace: true })
    },
  })

  const signedInAs = state.status === 'signed-in' ? state.me.email : null
  const rightPerson = signedInAs !== null && signedInAs.toLowerCase() === inv.email.toLowerCase()

  return (
    <AuthShell title={`Join ${inv.tenant_name}`} subtitle="You have been invited to ZipZy DBA." footer={<HomeLink />}>
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4">
        <div className="flex items-start gap-3 rounded-lg border bg-muted/50 p-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-accent text-accent-foreground" aria-hidden>
            <Building2 className="size-5" />
          </span>
          <div className="min-w-0 text-sm">
            <p className="font-medium">{inv.tenant_name}</p>
            <p className="text-muted-foreground">
              {inv.invited_by_name ? `${inv.invited_by_name} invited you` : 'You are invited'} as{' '}
              <span className="font-medium text-foreground">{inv.role_name}</span>.
            </p>
            <p className="mt-1 text-xs break-words text-muted-foreground">For {inv.email}</p>
            <p className="text-xs text-muted-foreground">Valid until {formatDateTime(inv.expires_at)}</p>
          </div>
        </div>

        {accept.isError && (
          <Alert variant="destructive">
            <AlertDescription>{describeError(accept.error)}</AlertDescription>
          </Alert>
        )}

        {state.status === 'loading' ? (
          <Skeleton className="h-9 w-full" />
        ) : state.status === 'signed-out' ? (
          <div className="grid gap-2">
            <p className="text-sm text-muted-foreground">Sign in or create an account with {inv.email} to accept.</p>
            <Button asChild>
              <Link to="/signup" state={{ from: here, email: inv.email }}>
                Create an account
              </Link>
            </Button>
            <Button asChild variant="outline">
              <Link to="/login" state={{ from: here, email: inv.email }}>
                I already have an account
              </Link>
            </Button>
          </div>
        ) : rightPerson ? (
          <Button onClick={() => accept.mutate()} busy={accept.isPending} className="w-full">
            Accept and join
          </Button>
        ) : (
          <div className="grid gap-3">
            <Alert variant="warning">
              <AlertDescription>
                You are signed in as <span className="font-medium">{signedInAs}</span>, but this invitation is for{' '}
                <span className="font-medium">{inv.email}</span>.
              </AlertDescription>
            </Alert>
            <Button variant="outline" onClick={() => void logout()}>
              Sign out and switch account
            </Button>
          </div>
        )}
      </div>
    </AuthShell>
  )
}

function HomeLink() {
  return (
    <Link to="/" className="font-medium text-primary underline-offset-4 hover:underline">
      Go to ZipZy DBA
    </Link>
  )
}