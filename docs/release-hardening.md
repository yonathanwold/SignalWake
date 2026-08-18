# Phase 9 release hardening

Phase 9 makes the existing SIGNALWAKE product safer and more predictable to
run. It does not claim a hosted deployment, complete national infrastructure
coverage, or an enterprise observability platform.

## Runtime boundaries

- API list responses are bounded by endpoint limits. Events, infrastructure,
  assessments, replay, lineage, scenarios, and graph responses retain their
  documented limits and cursor/page contracts.
- Graph relationship endpoints scope both endpoints in the database query when
  a filtered graph context is requested. `GraphEngine` memoizes structural
  metrics only for the lifetime of one request-local engine; there is no stale
  process-wide graph cache.
- Replay uses bounded knowledge-time scans and returns a `truncated` signal.
  SQLite geometry filtering is deterministic fixture behavior, not a claim of
  production-scale spatial throughput.
- Migration `009_query_bounds.sql` adds indexes for event ordering,
  relationship endpoint/type lookups, and event/asset assessment ordering.
  `scripts/validate_migrations.py` checks names and contiguous numbering without
  connecting to a database.
- Graph edge pages use a window count so page rows and totals come from one SQL
  snapshot; only an out-of-range empty page uses a fallback count to preserve
  the existing total contract.

## API security

CORS is configured with `CORS_ORIGINS` (comma-separated) and
`CORS_ALLOW_CREDENTIALS`. The settings validator rejects a wildcard origin when
credentials are enabled; local origins are the safe default. Responses include
`X-Request-ID`, `X-Content-Type-Options`, `X-Frame-Options`,
`Referrer-Policy`, `Permissions-Policy`, and `Cache-Control: no-store`.
These are API response protections, not a substitute for a TLS-terminating
reverse proxy, authentication, authorization, or a secret manager.

The infrastructure importer accepts local `--file` fixtures or a caller-owned
HTTP(S) GeoJSON URL. URL imports reject credentials, localhost, loopback,
private/link-local/reserved/metadata targets, unresolved hosts, unsafe schemes,
and redirects to unsafe targets. Redirects are limited to three hops and the
response body to 10 MiB; feature collections are limited to 100,000 records.
Timeouts are bounded to 120 seconds. Local fixtures remain available without a
network. Import errors are operator-facing categories/messages and redact URLs;
raw payloads are persisted only as the source record required for provenance.
The HTTP client does not trust proxy environment variables. DNS is resolved
and checked at each redirect, but complete DNS-rebinding protection requires a
pinned resolver or network egress policy outside this application.

NWS/USGS adapters retain their bounded timeout/retry behavior and source
isolation. A malformed feature is skipped and counted rather than blocking the
other source. Retries and source-scoped payload hashes preserve idempotency.
Logs do not include request bodies or full raw payloads, and exception text is
bounded with URL redaction.

## Demo and source labels

`LIVE` means a successful source fetch and persistence pass. `DEMO` means a
checked-in deterministic fixture fallback and is always labeled as such.
Historical Replay rows are labeled `HISTORICAL` and are knowledge-time
projections, not newly observed events. Infrastructure is `REFERENCE`; graph
edges and assessments are `DERIVED`. The fixture files are representative
tests, not complete source datasets. No disaster history, impact, outage,
economic-loss, dependency, or deployment fact is fabricated.

## Container and CI checks

`apps/api/Dockerfile` installs only runtime dependencies and runs as the
unprivileged `signalwake` user. `apps/web/Dockerfile` uses a multi-stage
standalone Next.js build and runs as `nextjs`. Compose binds local ports to
loopback, parameterizes Postgres credentials, creates PostGIS through the
checked-in initialization SQL, and keeps API/web behind the optional `app`
profile. Change the credentials before using any shared environment.
Compose accepts a complete `DATABASE_URL` override. If a database username or
password contains URI delimiters, percent-encode those components in the
override; the simple local default is not a general secret-encoding facility.

CI runs backend Ruff lint, a format gate for Phase 9 files, the full API pytest
suite, migration validation, frontend lint/typecheck/build, and Compose config
validation. Docker image builds and live PostGIS `EXPLAIN` checks are not
claimed unless explicitly run in the target environment.

## Deployment prerequisites and limitations

Before a real deployment, provide TLS and an authenticated reverse proxy,
non-default database credentials, a managed Postgres/PostGIS instance with
numbered migrations applied, an allowlisted CORS origin, secret/configuration
management, backups, log retention, and a durable metrics/alerting backend.
Run API and web smoke checks from a clean environment and verify the actual
source terms and imported dataset coverage. The repository does not include a
worker scheduler, auth system, queue, multi-region failover, or a hosted URL.
