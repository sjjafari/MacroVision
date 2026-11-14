# Changelog

All notable MacroVision release changes are documented here.

## 0.8.0

MacroVision v0.8.0 delivers the Persian Web MVP on top of the vintage-aware v0.7 Analytics foundation. The release remains an evidence and research platform: it does not generate trading signals, execute broker orders, or perform hidden browser-side financial calculations.

### Persian Web MVP

- Implements all nine approved Persian RTL routes: home, markets, macro, indicator catalog/detail, comparison, research, methodology, and about.
- Connects home/markets/macro dashboards to bounded persisted read models with exact Decimal evidence, explicit missing/stale/incomparable states, responsive ECharts, and accessible exact-value tables.
- Adds a reviewed indicator catalog with current and historical as-of snapshots, cutoff-aware revisions, source/methodology metadata, and current-only related Analytics lineage.
- Adds a bounded multi-series comparison contract for at most four raw/derived series with explicit frequency and axis semantics and no implicit alignment, resampling, filling, or interpolation.
- Adds a private research workspace for the nine registered versioned Analytics transformations, explicit bounded execution, persisted outputs, missingness, and point lineage.
- Completes reviewed Persian Methodology and About surfaces.

### Publication and security

- Adds explicit publication eligibility independent from operational state and private curation; non-eligible indicators fail closed.
- Adds public-safe indicator projections and a GET-only rate-limited public API namespace while keeping dashboards, comparison, research, management reads, and all mutations authenticated.
- Adds production trusted-ingress RBAC, GitHub OAuth2 Proxy sessions backed by Redis, same-origin mutation checks, audit events, NGINX TLS/auth_request/rate limiting, and internal-only application/database networking.
- Adds PostgreSQL production topology, backup procedure, isolated restore verification, hardened backend/web containers, deployment secret contract, and CI validation of gateway invariants.
- Production frontend dependency audit at the high threshold is enforced in CI.

### Data and reproducibility

- Preserves exact Decimal strings for business values and limits JavaScript Number conversion to chart geometry.
- Historical reads retain no-look-ahead behavior and suppress future revisions/evidence.
- GET reader routes do not trigger provider synchronization or Analytics execution.
- Keeps Alembic head at `20260726_0009`; v0.8.0 adds no database migration.

### Release boundary

- The repository is deployment-ready but is not automatically published to the Internet. A real deployment still requires operator-supplied OAuth credentials, TLS certificates, production secrets, authorized-user lists, PostgreSQL backup/restore verification, and deployment smoke in the target environment.

## 0.7.0

MacroVision v0.7.0 introduces the vintage-aware Macro Analytics Engine while preserving
the platform principle that research transformations are decision intelligence, not
predictions, recommendations, or trading signals.

### Macro Analytics

- Adds derived-series definitions with immutable semantic versions and ordered,
  server-snapshotted Macro Data inputs.
- Implements nine deterministic transformations: difference, percent change,
  year-over-year percent change, ratio, spread, moving average, rolling standard
  deviation, rolling z-score, and index rebasing.
- Resolves source observations with no look-ahead, selecting the exact original or
  revision vintage known at the calculation cutoff.
- Persists immutable runs, exact Decimal outputs, missingness classifications, and
  point-level lineage back to source observations or revisions.
- Separates request, snapshot, and reusable identities to provide deterministic
  idempotency without exposing private fingerprints.
- Preserves failed-run audits and supports explicit compatible retries without
  overwriting prior execution history.

### Public API

- Adds strict definition management, immutable version creation, and explicit
  enable/disable operations with optimistic concurrency.
- Adds bounded synchronous execution with distinct created, reusable-completed, and
  active-request dispositions.
- Adds deterministic run listing, exact-run observations, latest results, ranged reads,
  historical knowledge-cutoff as-of reads, and exact point-lineage retrieval.
- Publishes closed response enums and consistent shared error envelopes while excluding
  request, snapshot, reusable, and parameter fingerprints from OpenAPI and responses.

### Operations and security

- Adds a deterministic offline SQLite benchmark and an environment-gated PostgreSQL
  benchmark that verifies Alembic head, runs safely in a dedicated database, and cleans
  only benchmark-owned rows.
- The 10,000-output SQLite reference cases completed in approximately 13–14 seconds;
  idempotent replay completed in approximately 1.7 seconds on the development machine.
- Retains the credential-redaction, bounded provider HTTP, immutable audit, migration,
  and PostgreSQL enum-lifecycle hardening delivered through v0.6.
- Supports the complete migration chain through Alembic revision `20260726_0009`.

### Deferred scope

- No Analytics worker or queue.
- No automatic recomputation.
- No provider-scheduler integration for Analytics.
- No derived-to-derived dependencies.
- No prediction, recommendation, trading, or brokerage behavior.
