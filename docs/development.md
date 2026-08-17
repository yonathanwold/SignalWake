# Development notes

## Project layout

- `apps/api/app` — FastAPI app, domain models, adapters, repository, and services.
- `apps/api/tests` — fixture-only adapter and API tests; no external calls.
- `apps/web/app` — Next.js App Router routes.
- `apps/web/components` — shared map, feed, shell, and future-route UI.
- `apps/web/lib` — canonical frontend types and API/demo data access.
- `infra/docker-compose.yml` — Postgres/PostGIS target service.

## Data classification

Every visible event is marked `LIVE` or `DEMO`, and normalized source fields are marked `DERIVED` in the interface. A demo event is never described as an observed live event. No code path uses an LLM or makes infrastructure-impact claims.

## Adapter behavior

Adapters send a descriptive user-agent, enforce a timeout, retry transient 429/5xx responses with bounded exponential backoff, and return structured errors for malformed JSON or missing fields. A fetch is written as a raw observation before event normalization. Tests use checked-in JSON fixtures.

## Browser verification

The map has a MapLibre-ready runtime boundary, but the first slice uses a deterministic SVG fallback when `NEXT_PUBLIC_MAP_STYLE_URL` is empty. This keeps the shell usable without a token or network tile service and labels the fallback in the UI. A later milestone can mount MapLibre against the same event data without changing the feed or API contract.

