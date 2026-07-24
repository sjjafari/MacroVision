# MacroVision

MacroVision is an Investment Decision Intelligence Platform. Version 0.5.0 provides a
local, auditable foundation for investor profiles, risk budgets, hypothesis-driven
research journals, transaction-driven portfolio accounting, and versioned investment
decision cases, immutable-vintage macroeconomic and market-data storage, and manual
synchronization with FRED through a provider-independent integration layer. It is not
a trading signal bot and does not connect to brokers or execute trades.

## Decision principles

- Preserve capital before pursuing return.
- Treat cash as a valid asset allocation.
- Begin decisions with a falsifiable hypothesis.
- Express conclusions as probabilities and confidence levels, never certainty.
- Keep Research AI (evidence gathering) and Critic AI (adversarial review) as separate roles.
- Learn only from outcomes and lessons documented in the research journal.

The API makes these principles explicit through required supporting evidence, opposing
evidence, critic review, invalidation conditions, probability, and confidence fields.

## Architecture

```text
HTTP / OpenAPI       src/macrovision/api.py, main.py
Validation           src/macrovision/schemas.py
Decision workflows   src/macrovision/services.py
Persistence          src/macrovision/models.py, database.py
Portfolio API        src/macrovision/portfolio_api.py
Portfolio accounting src/macrovision/portfolio_services.py
Portfolio contracts  src/macrovision/portfolio_schemas.py
Portfolio storage    src/macrovision/portfolio_models.py
Decision API         src/macrovision/decision_api.py
Decision rules       src/macrovision/decision_services.py
Decision contracts   src/macrovision/decision_schemas.py
Decision storage     src/macrovision/decision_models.py
Exact value types    src/macrovision/persistence_types.py
Shared contracts     src/macrovision/contracts.py, errors.py
Macro Data API       src/macrovision/macro_data_api.py
Macro Data services  src/macrovision/macro_data_services.py
Macro Data storage   src/macrovision/macro_data_models.py
Provider API         src/macrovision/provider_api.py
Provider contracts   src/macrovision/provider_contracts.py
Provider sync        src/macrovision/provider_services.py
FRED adapter/client  src/macrovision/fred_provider.py
Schema history       migrations/
Configuration        src/macrovision/config.py
```

The local release uses FastAPI, Pydantic, SQLAlchemy 2, Alembic, and SQLite. Database
schema changes are owned by Alembic rather than application startup.

## Prerequisites

- Python 3.11 or later
- Windows PowerShell 5.1 or later
- Optional: Docker Desktop

## Install on Windows

From the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\setup.ps1
```

The script creates `.venv`, installs the application and development tools, copies
`.env.example` to `.env` when `.env` does not exist, and applies all migrations.

Manual equivalent:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m alembic upgrade head
```

## Run

```powershell
.\scripts\run.ps1
```

Then open:

- API health: http://127.0.0.1:8000/health
- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI schema: http://127.0.0.1:8000/openapi.json

## Quality checks

```powershell
.\scripts\check.ps1
```

Or run each check:

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pytest
```

## Docker

```powershell
docker build -t macrovision:0.5.0 .
docker run --rm -p 8000:8000 -v macrovision-data:/data macrovision:0.5.0
```

The container applies pending migrations before starting the API and persists SQLite
data in the `macrovision-data` volume.

## API workflow

1. Create an investor profile and its risk profile/risk budget with
   `POST /api/v1/investors`.
2. Record independent research and critic review with `POST /api/v1/journals`.
3. Close the journal with a documented outcome and lesson using
   `POST /api/v1/journals/{journal_id}/close`.

This version is for research and decision documentation only. It does not offer
personalized financial advice, authentication, AI model calls,
portfolio optimization, real trading, or brokerage integration.

The Research Journal endpoints are deprecated compatibility APIs. New decision records
should use the Decision Engine workflow below. A legacy journal always starts in `draft`,
can be closed only once, and is terminal after closure; its outcome, lessons, and closure
timestamp cannot be overwritten.

## Portfolio workflow (v0.2)

Portfolio accounting is driven only by immutable transactions. Financial amounts use
decimal arithmetic, and every portfolio has one base valuation currency.

1. Create a portfolio with `POST /api/v1/portfolios`.
2. Fund cash with a `deposit` transaction at
   `POST /api/v1/portfolios/{portfolio_id}/transactions`.
3. Add or increase positions with `buy`; reduce or remove positions with `sell`.
4. Record `withdrawal`, `fee`, `dividend`, and `interest` transactions through the same
   endpoint.
5. Update a position's manually supplied valuation price with
   `PUT /api/v1/portfolios/{portfolio_id}/positions/{position_id}/price`.
6. Read total value, cost basis, realized/unrealized P&L, and allocations from
   `GET /api/v1/portfolios/{portfolio_id}/summary`.
7. Capture an immutable point-in-time valuation with
   `POST /api/v1/portfolios/{portfolio_id}/snapshots`.

Buy and sell transactions must use the portfolio base currency. Cash can be tracked in
other currencies, but foreign cash is reported separately and excluded from total
base-currency value because v0.2 has no exchange-rate provider. Current prices are
entered explicitly; MacroVision does not fetch market prices or submit trades.

Financial values are rounded explicitly using round-half-even to eight decimal places;
quantities support ten decimal places. SQLite stores these values as scaled 64-bit
integers so Decimal values round-trip exactly. Requests outside the supported storage
range are rejected. Trade cost basis and sell P&L are gross of fees: fees are separate,
immutable expense transactions that reduce cash and portfolio-level realized P&L, but
do not rewrite a position's average cost.

Version 0.4.1 applies aggregate optimistic concurrency to every financial mutation. A
concurrent stale mutation is rolled back in full and returns HTTP `409 Conflict`; no
transaction can be committed without its matching cash and position changes. Clients do
not send a lock version: after a 409 they should reload the portfolio, reassess available
cash/quantity, and submit a new request only if it remains valid.

## Decision workflow (v0.3)

Decision cases separate hypotheses, supporting evidence, opposing evidence, independent
criticism, invalidation conditions, and documented outcomes. Probability and confidence
are separate six-decimal values from zero to one; they communicate uncertainty rather
than certainty.

1. Create a draft with `POST /api/v1/decisions`.
2. Add one or more hypotheses with
   `POST /api/v1/decisions/{decision_id}/hypotheses`.
3. Add `supporting` and `opposing` evidence separately through
   `POST /api/v1/decisions/{decision_id}/evidence`.
4. Record an independent critic review at
   `POST /api/v1/decisions/{decision_id}/critic-reviews`.
5. Define explicit observable invalidation rules through
   `POST /api/v1/decisions/{decision_id}/invalidation-rules`.
6. Activate only after every completeness gate passes with
   `POST /api/v1/decisions/{decision_id}/activate`.
7. Change probability, confidence, or rationale only through
   `POST /api/v1/decisions/{decision_id}/revise`; this appends a version rather than
   overwriting history.
8. Invalidate an active case with
   `POST /api/v1/decisions/{decision_id}/invalidate`, or close it with an outcome,
   lessons, and accuracy assessment at
   `POST /api/v1/decisions/{decision_id}/close`.
9. Read the immutable version history from
   `GET /api/v1/decisions/{decision_id}/history`.

Draft and under-review cases can accumulate documented research. Active cases can accept
new evidence but must use a revision to change their probability, confidence, or
rationale. Invalidated and closed cases are terminal. Decision records are research and
governance artifacts only: v0.3 does not call AI providers, generate automated
recommendations, or connect to brokers.

## Macro Data workflow (v0.4)

The Macro Data Engine stores manually supplied or file-derived macroeconomic and market
series without connecting to external providers. Values use exact Decimal arithmetic and
are stored as signed 64-bit integers scaled to eight decimal places. All API timestamps
must include an offset and are normalized to UTC.

1. Register a documented source with `POST /api/v1/data-sources`.
2. Define a series and its frequency, unit, geography, seasonal-adjustment status, source,
   publication lag, optional currency, metadata, and optional quality thresholds through
   `POST /api/v1/data-series`.
3. Add an observation with
   `POST /api/v1/data-series/{series_id}/observations`. A present observation requires an
   exact value; a missing observation requires `status=missing` and `value=null`.
4. Correct an existing series/timestamp by posting it again with `revision_reason`.
   MacroVision appends an immutable `DataRevision`; the original observation is not
   overwritten.
5. Read the current value from `GET /api/v1/data-series/{series_id}/latest`, the complete
   ordered series from `GET /api/v1/data-series/{series_id}/observations`, a historical
   vintage from `GET /api/v1/data-series/{series_id}/observations/as-of?as_of=...`, and an
   observation's revision history from
   `GET /api/v1/data-series/{series_id}/observations/{observation_id}/revisions`.
6. Import validated rows through `POST /api/v1/data-imports`. Imports are atomic by
   default. Set `partial_mode=true` to retain valid rows and explicitly count rejected
   domain-invalid rows. Reusing an idempotency key returns the original batch and creates
   no duplicate observations. An atomic failure preserves a failed batch with its
   timestamp, safe summary, and immutable row error while rolling back every observation
   and revision. Partial imports retain a bounded error record for each rejected row.
7. Review detected range, frequency, staleness, duplicate, timestamp, and change issues at
   `GET /api/v1/data-quality/issues`; acknowledge or resolve them through their explicit
   action endpoints.
8. Patch mutable series metadata with `PATCH /api/v1/data-series/{series_id}` using the
   current `expected_lock_version`. Quality-issue transitions use the same stale-write
   protection.

Historical observations, revisions, and completed import batches are immutable. Quality
issues never rewrite source data. World Bank, IMF, central-bank and other external
integrations, web scraping, schedulers, AI analysis, trading recommendations,
authentication, brokers, and FX conversion remain intentionally excluded.

Import request limits are configurable through `MACROVISION_MAX_IMPORT_ROWS`,
`MACROVISION_MAX_IMPORT_NOTES_LENGTH`, and
`MACROVISION_MAX_IMPORT_ERROR_MESSAGE_LENGTH`; `.env.example` contains safe local
defaults. MacroVision v0.5.0 has no authentication. Any deployment must remain on a
trusted private network and must not be exposed directly to the public internet.

## External providers and FRED workflow (v0.5)

External providers implement a shared contract for identity, metadata retrieval,
observation retrieval, normalization, connectivity checks, and controlled errors. The
Macro Data Engine consumes normalized provider records and has no dependency on FRED
response structures. Future providers can implement this contract without changing
Macro Data persistence, while the abstraction intentionally contains only behavior
demonstrated by the FRED integration.

Configure the API key in `.env`; it is read only from runtime configuration and is never
stored, logged, returned, or included in import metadata:

```dotenv
MACROVISION_FRED_API_KEY=
MACROVISION_FRED_BASE_URL=https://api.stlouisfed.org/fred
MACROVISION_PROVIDER_REQUEST_TIMEOUT_SECONDS=10
MACROVISION_PROVIDER_MAX_OBSERVATIONS=10000
MACROVISION_PROVIDER_MAX_RESPONSE_BYTES=5000000
MACROVISION_PROVIDER_MAX_RETRIES=2
```

Set `MACROVISION_FRED_API_KEY` privately to the key issued for your account; do not put
credentials in requests, source control, logs, or synchronization metadata.
`MACROVISION_FRED_BASE_URL` is configurable for deployment consistency but is restricted
to the official `https://api.stlouisfed.org/fred` endpoint so credentials cannot be
forwarded to an arbitrary host.

Synchronize a series manually:

```http
POST /api/v1/providers/fred/series/CPIAUCSL/sync
Content-Type: application/json

{
  "internal_series_code": "FRED.CPIAUCSL",
  "category": "inflation",
  "geography": "US",
  "is_active": true,
  "metadata_notes": "Headline CPI used in the macro dashboard",
  "observation_start": "2020-01-01"
}
```

The provider creates or reuses the `FRED` source and provider-linked series, then imports
normalized observations through the same immutable observation/revision rules as manual
data. Values are parsed directly as `Decimal` and stored at exact eight-decimal
precision. FRED's `.` marker becomes `status=missing` with `value=null`; no placeholder
number is invented. Values with more than eight decimal places are rejected rather than
silently rounded by provider synchronization.

FRED realtime fields are vintage dates, not exact publication timestamps. MacroVision
stores them separately as provider vintage dates and leaves `publication_timestamp`
null unless an upstream provider genuinely supplies an exact timestamp. The ingestion
timestamp records when MacroVision learned the value. Provider request scope and safe
provenance are retained without unrestricted upstream payloads.

Historical synchronization supports one exact FRED realtime date at a time:
`realtime_start` and `realtime_end` must both be supplied and equal. Multi-vintage
ranges are rejected because their output semantics cannot be represented as one current
observation per date without ambiguity.

Generated synchronization keys include a fingerprint of normalized provider data.
Replaying an unchanged response returns the prior import batch. Changed historical
values, including missing-to-value and value-to-missing transitions, append immutable
revisions. An explicitly supplied idempotency key cannot be reused for different data.

Normal tests use deterministic mocked HTTP transports and require no FRED credentials.
An optional live smoke test runs only when both
`MACROVISION_ENABLE_LIVE_FRED_TESTS=true` and a valid
`MACROVISION_FRED_API_KEY` are present. Version 0.5 remains manual-only: it adds no
scheduler, background worker, bulk catalog ingestion, AI analysis, authentication,
recommendation, or trading behavior.

Synchronization is performed synchronously in the API request and can occupy one worker
while bounded upstream retries complete. The endpoint has no authentication in v0.5 and
must be exposed only on a trusted private network.

## Data contracts (v0.4.2)

All public timestamps must contain an explicit UTC offset. Positive, negative, and
daylight-saving offsets are normalized to UTC and responses always serialize an explicit
UTC offset. Legacy naive database timestamps are interpreted as UTC by migration
`20260724_0006`. SQLite stores normalized naive UTC internally; PostgreSQL uses
`TIMESTAMPTZ`.

Legacy bounded ratios—including liquidity need, risk limits, journal probability, and
confidence—use exact signed integers scaled to six decimal places. API JSON represents
these values as fixed six-decimal strings. Portfolio money precision remains eight
decimals and Macro Data values remain eight decimals.

Expected `404`, `409`, and `422` responses use a shared contract with `code`, safe
`message`, optional bounded `details`, and a compatibility `detail` field. List endpoints
accept `limit` (default 100, maximum 200) and `offset` (default 0), retain their existing
array response bodies, and use deterministic ID tie-breaking.

Quality-issue listing and retrieval are read-only. Run stale detection explicitly with
`POST /api/v1/data-quality/scans/stale`; repeated scans do not create duplicate open
issues. Read immutable acknowledgement and resolution history from
`GET /api/v1/data-quality/issues/{issue_id}/history`.

The GitHub Actions workflow runs Ruff, mypy, pytest, SQLite migration-backed tests, and a
PostgreSQL 16 migration cycle. For local PostgreSQL work, install the `postgres` optional
dependency and set `MACROVISION_DATABASE_URL`, for example:

```text
postgresql+psycopg://macrovision:macrovision@localhost:5432/macrovision
```
