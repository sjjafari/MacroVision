# MacroVision Web

MacroVision Web v0.8.0 is the Persian RTL interface for the vintage-aware MacroVision backend. All nine approved MVP routes are implemented: dashboards, reviewed indicators, indicator detail/as-of evidence, bounded multi-series comparison, private Analytics research, methodology, and about.

Server Components and server actions use the generated OpenAPI client through a server-only backend URL. Exact Decimal strings remain authoritative for labels, tables, tooltips, comparisons, and evidence; JavaScript Number conversion is limited to finite ECharts geometry. Missing values remain gaps and are never mapped to zero.

In private-preview mode the indicator workspace uses reviewed-private contracts. In production mode it switches to the public indicator projection, whose backend allowlist is independent from operational `is_active` and private curation. About, Methodology, and publication-eligible indicator pages may be unauthenticated; dashboards, comparison, research, management reads, and mutations remain behind the production trusted-ingress/RBAC boundary.

The research workspace exposes only the nine registered versioned Analytics transformations. Creating a definition or executing a run is an explicit server-side mutation protected by the research role and same-origin mutation checks. Reader GETs never trigger Analytics execution or provider synchronization.

The comparison workspace accepts at most four raw or persisted-derived selections. The backend returns independent timelines with explicit frequency mismatch and axis semantics; neither backend reader nor browser silently aligns, resamples, fills, interpolates, or invents Ratio/Spread results.

Historical indicator mode uses an aware UTC cutoff, suppresses future revisions, and intentionally suppresses current-only related-derived/lineage evidence. Publication and production security do not change the underlying no-look-ahead semantics.

Deterministic production-style visual preview (PowerShell):

```powershell
cd D:\Projects\MacroVision\web
$env:SMOKE_VISUAL_HOLD_MS = "600000"
npm.cmd run smoke
```

The smoke command prints its dynamically allocated localhost URL. During the hold,
browse `/fa`, `/fa/markets`, `/fa/macro`, `/fa/indicators`, and the populated detail
route printed by the script. Afterwards run `Remove-Item Env:SMOKE_VISUAL_HOLD_MS`.

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


## Phase 4 comparison

`/fa/compare` is a private research surface for at most four reviewed raw or persisted derived series. URL-backed selections and date bounds are sent to the server-only comparison transport. The backend returns independent series with explicit frequency warnings and axis identities; the browser does not align, resample, fill, interpolate, or calculate financial transformations. Exact Decimal strings remain authoritative in tables and tooltips, while finite `Number` projection is restricted to ECharts geometry. An optional historical cutoff uses persisted no-look-ahead reads.\n

## Phase 5 private research

`/fa/research` is a trusted-network mutation surface. It can create versioned definitions for the nine approved Analytics transformations and explicitly execute bounded runs through server-only POST transport. Persisted output, missing reasons, run metadata, and point-level lineage are inspectable. It must not be publicly exposed before Phase 6 authentication, RBAC, secure sessions, CSRF protection, and rate limiting are complete.\n