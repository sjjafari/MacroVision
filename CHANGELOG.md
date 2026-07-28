# Changelog

All notable MacroVision release changes are documented here.

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
