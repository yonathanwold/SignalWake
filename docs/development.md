# Development notes

## Project layout

- `apps/api/app` — FastAPI app, domain models, adapters, repository, and services.
- `apps/api/tests` — fixture-only adapter, ingestion, and API tests; no external calls.
- `apps/web/app` — Next.js App Router routes.
- `apps/web/components` — shared map, feed, shell, and future-route UI.
- `apps/web/lib` — canonical frontend types and API/demo data access.
- `infra/docker-compose.yml` — Postgres/PostGIS target service.

## Data classification

Every visible event is marked `LIVE` or `DEMO`, and normalized source fields are marked `DERIVED` in the interface. A demo event is never described as an observed live event. No code path uses an LLM or makes infrastructure-impact claims.

## Adapter behavior

Adapters send a descriptive user-agent, enforce a timeout, retry transient 429/5xx responses with bounded exponential backoff, and return structured errors for malformed JSON or missing fields. `ingest_once` runs one bounded pass over every adapter, records source attempt/success/error metadata, preserves each valid raw payload, and writes canonical `LIVE` events idempotently. Malformed features are logged and skipped without blocking the other source. Tests use checked-in JSON fixtures and monkeypatch the fetch boundary, so CI never calls NWS or USGS.

## Startup ingestion and fallback

`INGEST_ON_STARTUP=true` is the default. FastAPI runs `ingest_once` once during startup; it is intentionally bounded and is not a permanent queue or scheduler. `USE_DEMO_DATA=true` enables a source-scoped fixture fallback only when that source's live fetch fails or yields no usable normalized events. A source with successful `LIVE` events is never replaced by fixture rows, and demo rows never change live source freshness metadata. Set `USE_DEMO_DATA=false` when an empty live result should remain empty.

## Browser verification

The Operational Map mounts MapLibre GL JS with a self-contained dark style, local worker assets, and GeoJSON sources for canonical event points and polygons. It needs no token or external tile service. The existing SVG map remains an explicit fallback if MapLibre initialization fails, and the UI labels which runtime is active.
