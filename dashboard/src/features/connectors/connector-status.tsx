import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

const STATUS: Record<string, { label: string; variant: 'success' | 'secondary' | 'outline' | 'destructive'; dot: string }> = {
  online: { label: 'Online', variant: 'success', dot: 'bg-success' },
  offline: { label: 'Offline', variant: 'secondary', dot: 'bg-muted-foreground' },
  pending: { label: 'Waiting for install', variant: 'outline', dot: 'bg-warning animate-pulse' },
  revoked: { label: 'Revoked', variant: 'destructive', dot: 'bg-destructive' },
}

/** Coloured dot + word, so status never depends on colour alone. */
export function ConnectorStatusBadge({ status }: { status: string }) {
  const s = STATUS[status] ?? STATUS.offline
  return (
    <Badge variant={s.variant}>
      <span className={cn('size-1.5 rounded-full', s.dot)} aria-hidden />
      {s.label}
    </Badge>
  )
}