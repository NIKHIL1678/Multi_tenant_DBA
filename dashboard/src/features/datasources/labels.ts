// Display names for database engines and statuses. Kept apart from components so both
// the page and its dialogs can use them.

export const ENGINE_LABELS: Record<string, string> = {
  postgres: 'PostgreSQL',
  mysql: 'MySQL',
  mariadb: 'MariaDB',
  mongodb: 'MongoDB',
  mssql: 'SQL Server',
}

export function engineLabel(engine: string): string {
  return ENGINE_LABELS[engine] ?? engine
}

export const DATASOURCE_STATUS: Record<string, { label: string; variant: 'success' | 'destructive' | 'secondary' }> = {
  connected: { label: 'Connected', variant: 'success' },
  error: { label: 'Unreachable', variant: 'destructive' },
  unknown: { label: 'Not reporting', variant: 'secondary' },
}