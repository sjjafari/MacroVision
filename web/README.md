# MacroVision Web

Phase 1 provides the private Persian RTL frontend foundation for MacroVision. The nine
route shells intentionally contain no live dashboard data and make no provider calls.

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

Open `http://127.0.0.1:3000/fa`. Static route shells work without a running backend.
The same-origin `/api/v1/*` proxy requires the configured backend only when called.

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

`npm run smoke` uses a localhost-only fake upstream. It verifies the production build,
all nine routes, redirects, transparent error handling, query preservation, and exact
Decimal strings without contacting FRED or any public provider.

## Security boundary

This frontend is a private foundation preview. Authentication, authorization, secure
sessions, CSRF protection, rate limiting, publication eligibility, and public
deployment are not implemented or approved. `robots.txt` is an indexing hint, not an
access-control mechanism.
