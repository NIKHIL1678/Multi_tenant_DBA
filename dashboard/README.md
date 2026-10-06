# ZipZy DBA — dashboard

React + Vite + TypeScript, Tailwind CSS, React Router, TanStack Query.

## Run locally

1. Start the API: `cd ../control-plane` then `uv run uvicorn app.main:app --reload` (port 8000)
2. Start the dashboard: `npm install` (first time) then `npm run dev`
3. Open http://localhost:5173 and sign in (demo: `owner@sharma.test` / `zipzy-demo-pass`)

The dev server forwards `/v1/*` to the API, so there is no CORS setup in development.

## Checks (same as CI)

```
npm run lint
npm run build
```

## Where things live

| Path | What |
|---|---|
| `src/lib/api.ts` | The only code that calls the backend: tokens, refresh, errors |
| `src/lib/auth.tsx`, `auth-context.ts` | Who is signed in |
| `src/lib/types.ts` | API response shapes |
| `src/pages/` | One file per screen |
| `src/components/` | Layout, auth guard, small UI pieces (`ui/`) |