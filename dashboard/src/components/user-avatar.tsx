import { initials } from '@/lib/format'
import { cn } from '@/lib/utils'

/** Round badge with a person's initials. */
export function UserAvatar({ name, className }: { name: string; className?: string }) {
  return (
    <span
      className={cn(
        'grid size-9 shrink-0 place-items-center rounded-full bg-accent text-xs font-semibold text-accent-foreground',
        className,
      )}
      aria-hidden
    >
      {initials(name)}
    </span>
  )
}