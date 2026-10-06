# ZipZy DBA — dashboard

React + Vite + TypeScript, Tailwind CSS with shadcn/ui-style components (Radix), React Router,
TanStack Query.

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

## API types

`src/types/api.d.ts` is generated from the backend. After changing the API:

```
cd ../control-plane && uv run python scripts/export_openapi.py   # writes dashboard/openapi.json
cd ../dashboard && npm run gen:api                               # writes src/types/api.d.ts
```

CI fails if either file is out of date.

## Where things live

| Path | What |
|---|---|
| `src/app/` | Router, auth guard, layouts (sidebar, top bar, company switcher, user menu) |
| `src/features/<area>/` | One folder per backend area: `api.ts` (data hooks) + its pages |
| `src/components/ui/` | Design-system pieces (button, card, dialog, table, …). Use these, never raw HTML styles |
| `src/components/` | Shared page pieces: page header, empty state, error box |
| `src/lib/` | API client, auth, theme, permissions, company context, helpers |
| `src/types/api.d.ts` | Generated API types (do not edit) |
| `src/index.css` | Design tokens: the only place colours, radius and font are defined |

## UI rules

- Colours only through tokens (`bg-primary`, `text-muted-foreground`, `border`…), never raw ones like `bg-blue-600`.
- Every screen works from 360 px wide: tables become cards, actions wrap under the title.
- Every data view has loading (skeleton), empty, error and no-access states.
- Hide actions with `can(Permission.X)`; the server still checks everything.