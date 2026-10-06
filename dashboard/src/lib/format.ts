/** "owner" -> "Owner", "backend_dev" -> "Backend dev" */
export function humanize(key: string): string {
  const s = key.replaceAll('_', ' ')
  return s.charAt(0).toUpperCase() + s.slice(1)
}

/** Initials for an avatar: "Anil Sharma" -> "AS", "dba@x.com" -> "D". */
export function initials(nameOrEmail: string): string {
  const parts = nameOrEmail.split('@')[0].split(/[\s._-]+/).filter(Boolean)
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : (parts[0]?.[0] ?? '?')).toUpperCase()
}

const dateFormat = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })
const dateTimeFormat = new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
const relativeFormat = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })

/** "6 Oct 2026" */
export function formatDate(iso: string): string {
  return dateFormat.format(new Date(iso))
}

/** "6 Oct 2026, 1:04 pm" (for tooltips and detail views) */
export function formatDateTime(iso: string): string {
  return dateTimeFormat.format(new Date(iso))
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
]

/** "in 6 days", "3 hours ago", "now" */
export function formatRelative(iso: string, now: number): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000)
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return relativeFormat.format(Math.trunc(seconds / size), unit)
  }
  return 'now'
}