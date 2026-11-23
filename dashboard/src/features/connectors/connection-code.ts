/**
 * Everything the Windows connector needs in one paste: this ZipZy's address and the one-time
 * token. Same format the connector decodes (zipzy_connector/desktop.py): "zipzy1." + base64url JSON.
 */
export function connectionCode(zipzyUrl: string, token: string): string {
  const json = JSON.stringify({ u: zipzyUrl, t: token })
  const b64 = btoa(String.fromCharCode(...new TextEncoder().encode(json)))
  return `zipzy1.${b64.replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')}`
}
