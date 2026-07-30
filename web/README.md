# MacroVision Web

Phase 1 provides the private Persian RTL frontend foundation for MacroVision. Web MVP
Phase 2B connects `/fa`, `/fa/markets`, and `/fa/macro` to the persisted dashboard
contracts added in Phase 2A. The remaining six Persian routes stay as shells.

The available private backend contracts are:

- `GET /api/v1/dashboards`
- `GET /api/v1/dashboards/{dashboard_code}`
- `GET /api/v1/dashboards/{dashboard_code}/summary`
- filtered `GET /api/v1/data-series`
- bounded current and as-of observation ranges

Dashboard summaries return only persisted state. Comparisons are computed by the
backend, missing metrics are explicit, and GET requests never execute Analytics.
Next.js Server Components fetch each definition and summary in parallel through a
server-only client with `cache: "no-store"` and a five-second timeout. Browser API
traffic remains same-origin under `/api/v1`; the configured FastAPI URL is never sent
to browser code.

The summary contract keeps point state separate from comparison state. A present point
remains available or stale even if its comparison is missing, incomparable, or has a
frequency mismatch. `basis_code` identifies the comparison period and `anchor_policy`
requires an exact point relationship; existing derived comparisons currently use
`same_observed_at` and never silently align adjacent dates. Raw freshness uses the
series threshold, while derived freshness is honestly `not_configured` until a reviewed
policy exists. `stale_metric_count` is derived from freshness status, and Decimal
overflow in a comparison is represented as an incomparable comparison rather than a
failed response.

The featured chart uses the definition's reviewed `featured_chart` flag and one bounded
raw or derived observation GET (maximum 200 points). Missing observations remain gaps.
All Decimal values remain strings: the UI groups digits using string operations, uses
the original exact values in labels, tooltips, and the accessible table, and performs
no browser financial calculation. ECharts receives the exact strings only as visual
geometry input.

Phase 2B adds no migration, provider request, implicit Analytics execution, frontend
mutation, authentication, or public deployment. Package and OpenAPI versions remain
`0.7.0`, Alembic head remains `20260726_0009`, and Phase 3 publication work remains
pending.

## Prerequisites

- Node.js 24 LTS (the exact development version is recorded in `../.nvmrc`)
- npm 11
- Python 3.12 with the MacroVision backend installed locally

## Install

```powershell
cd web
npm ci
Copy-Item .env.example .env.local
```

`MACROVISION_BACKEND_URL` is server-only. Never rename it with a `NEXT_PUBLIC_`
prefix. The local example points to `http://127.0.0.1:8000`.

## Development

```powershell
npm run dev
```

Open `http://127.0.0.1:3000/fa`. The three connected dashboard routes require the
configured backend. Other static route shells remain available without it. Browser
requests use the same-origin `/api/v1/*` proxy.

## API generation

From the repository root, export the deterministic contract:

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py `
  --output web\openapi\macrovision.openapi.json
```

Then generate TypeScript types:

```powershell
cd web
npm run api:generate
npm run api:check
```

The OpenAPI snapshot and `src/lib/api/generated/schema.ts` are committed artifacts.
Never edit the generated schema manually.

## Quality and production checks

```powershell
npm run lint
npm run typecheck
npm run test:run
npm run build
npm run smoke
```

`npm run smoke` uses a localhost-only fake upstream. It verifies the three connected
dashboards, all nine routes, bounded chart reads and gaps, redirects, transparent error
handling, query preservation, exact Decimal strings, and absence of mutation requests
without contacting FRED or any public provider.

## Security boundary

This frontend is a private foundation preview. Authentication, authorization, secure
sessions, CSRF protection, rate limiting, publication eligibility, and public
deployment are not implemented or approved. `robots.txt` is an indexing hint, not an
access-control mechanism.
