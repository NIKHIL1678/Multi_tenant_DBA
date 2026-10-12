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

const timeFormat = new Intl.DateTimeFormat('en-IN', { hour: 'numeric', minute: '2-digit' })

/** "1:04 pm" */
export function formatTime(iso: string): string {
  return timeFormat.format(new Date(iso))
}

/** Local calendar day key, e.g. "2026-10-06", for grouping by day. */
export function dayKey(iso: string | number): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** "Today", "Yesterday" or "6 Oct 2026". */
export function formatDay(iso: string, now: number): string {
  const key = dayKey(iso)
  if (key === dayKey(now)) return 'Today'
  if (key === dayKey(now - 86_400_000)) return 'Yesterday'
  return formatDate(iso)
}

const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']

/** 1536 -> "1.5 KB", 6_000_000_000 -> "5.6 GB" (binary units, as database tools show them). */
export function formatBytes(bytes: number): string {
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  const digits = unit === 0 || value >= 100 ? 0 : 1
  return `${value.toFixed(digits)} ${BYTE_UNITS[unit]}`
}

/** 90 -> "2 minutes", 200_000 -> "2 days" (largest whole unit; for uptimes and ages). */
export function formatDuration(seconds: number): string {
  const units: [string, number][] = [
    ['day', 86_400],
    ['hour', 3_600],
    ['minute', 60],
  ]
  for (const [unit, size] of units) {
    const n = Math.floor(seconds / size)
    if (n >= 1) return `${n} ${unit}${n === 1 ? '' : 's'}`
  }
  return 'less than a minute'
}

const countFormat = new Intl.NumberFormat('en-IN')
const compactFormat = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 })

/** 1234567 -> "12,34,567" (Indian grouping) */
export function formatCount(n: number): string {
  return countFormat.format(n)
}

/** 1234567 -> "1.2M" (for tight table cells) */
export function formatCompact(n: number): string {
  return compactFormat.format(n)
}

/** 0.9912 -> "99.1%" */
export function formatPercent(ratio: number): string {
  return `${(ratio * 100).toFixed(ratio >= 0.999 || ratio === 0 ? 0 : 1)}%`
}
