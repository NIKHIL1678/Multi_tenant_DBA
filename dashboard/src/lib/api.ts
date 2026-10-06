// The only place that talks to the backend.
//
// - The access token lives in this module's memory only (never localStorage), so a script
//   injected into the page cannot steal it from storage.
// - The refresh token is an httpOnly cookie the browser sends to /v1/auth/* by itself.
// - On a 401 we refresh once and retry. If that fails, the session is over.

import type { TokenOut } from '@/lib/types'

export type ApiErrorDetails = { field: string; message: string }[]

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly requestId: string | null
  readonly details: ApiErrorDetails | undefined

  constructor(status: number, code: string, message: string, requestId: string | null, details?: ApiErrorDetails) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
    this.details = details
  }
}

let accessToken: string | null = null
let onSessionExpired: (() => void) | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

/** Called once by the auth provider: what to do when the session can no longer be renewed. */
export function setSessionExpiredHandler(handler: () => void): void {
  onSessionExpired = handler
}

// ---- refresh ---------------------------------------------------------------------------------

let refreshing: Promise<boolean> | null = null

async function doRefresh(): Promise<boolean> {
  const res = await fetch('/v1/auth/refresh', { method: 'POST', credentials: 'include' })
  if (!res.ok) {
    accessToken = null
    return false
  }
  const body = (await res.json()) as TokenOut
  accessToken = body.access_token
  return true
}

/**
 * Get a new access token using the refresh cookie.
 *
 * Refresh tokens are single-use: replaying an old one signs the user out everywhere
 * (theft protection). So refreshes must never overlap:
 * - inside this tab, concurrent callers share one request;
 * - across tabs, a browser lock makes each tab wait its turn, and by then the cookie
 *   already holds the newest token.
 */
export function refreshAccessToken(): Promise<boolean> {
  if (!refreshing) {
    const run = () => doRefresh()
    const locked =
      typeof navigator !== 'undefined' && navigator.locks
        ? navigator.locks.request('zdba-refresh', run)
        : run()
    refreshing = locked.finally(() => {
      refreshing = null
    })
  }
  return refreshing
}

// ---- requests --------------------------------------------------------------------------------

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

function send(path: string, { method = 'GET', body, signal }: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`
  return fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'include',
    signal,
  })
}

async function toApiError(res: Response): Promise<ApiError> {
  const requestId = res.headers.get('X-Request-ID')
  try {
    const data = (await res.json()) as {
      error?: { code?: string; message?: string; request_id?: string; details?: ApiErrorDetails }
    }
    const e = data.error ?? {}
    return new ApiError(
      res.status,
      e.code ?? 'error',
      e.message ?? `Request failed (${res.status})`,
      e.request_id ?? requestId,
      e.details,
    )
  } catch {
    return new ApiError(res.status, 'error', `Request failed (${res.status})`, requestId)
  }
}

/** Call the API. Throws ApiError for any non-2xx answer. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let res = await send(path, options)

  if (res.status === 401 && !path.startsWith('/v1/auth/')) {
    if (await refreshAccessToken()) {
      res = await send(path, options)
    }
    if (res.status === 401) onSessionExpired?.()
  }

  if (!res.ok) throw await toApiError(res)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

/** A sentence to show the user, with the request id support needs. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return err.requestId ? `${err.message} (ref: ${err.requestId.slice(0, 8)})` : err.message
  }
  return 'Could not reach the server. Check your connection and try again.'
}


/** Server-side validation errors by field name, to show under each form input. */
export function fieldErrors(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError) || !err.details) return {}
  return Object.fromEntries(err.details.map((d) => [d.field, d.message]))
}

/** True for answers that mean "this does not exist for you" (also for a malformed id in the URL). */
export function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 422)
}