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