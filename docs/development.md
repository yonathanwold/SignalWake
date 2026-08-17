# Development notes

## Project layout

- `apps/api/app` — FastAPI app, domain models, adapters, importer, repository, and spatial services.
- `apps/api/tests` — fixture-only adapter, infrastructure, spatial, ingestion, and API tests; no external calls.
- `apps/web/app` — Next.js App Router routes.
- `apps/web/components` — shared map, feed, shell, and future-route UI.
- `apps/web/lib` — canonical frontend types and API/demo data access.
- `infra/docker-compose.yml` — Postgres/PostGIS target service.

## Data classification

Every visible event is marked `LIVE` or `DEMO`, and normalized source fields are marked `DERIVED` in the interface. A demo event is never described as an observed live event. No code path uses an LLM or makes infrastructure-impact claims.

Infrastructure assets are always classified `REFERENCE`. A source record can carry an operator, owner, status, or source-updated value only when the source supplies it; the normalizer does not fill missing domain facts. The browser keeps the event stream and reference layers visually and semantically separate.

## Adapter behavior

Adapters send a descriptive user-agent, enforce a timeout, retry transient 429/5xx responses with bounded exponential backoff, and return structured errors for malformed JSON or missing fields. `ingest_once` runs one bounded pass over every adapter, records source attempt/success/error metadata, preserves each valid raw payload, and writes canonical `LIVE` events idempotently. Malformed features are logged and skipped without blocking the other source. Tests use checked-in JSON fixtures and monkeypatch the fetch boundary, so CI never calls NWS or USGS.

## Startup ingestion and fallback

`INGEST_ON_STARTUP=true` is the default. FastAPI runs `ingest_once` once during startup; it is intentionally bounded and is not a permanent queue or scheduler. `USE_DEMO_DATA=true` enables a source-scoped fixture fallback only when that source's live fetch fails or yields no usable normalized events. A source with successful `LIVE` events is never replaced by fixture rows, and demo rows never change live source freshness metadata. Set `USE_DEMO_DATA=false` when an empty live result should remain empty.

## Browser verification

The Operational Map mounts MapLibre GL JS with a self-contained dark style, local worker assets, and GeoJSON sources for canonical event points, polygons, and infrastructure reference assets. It needs no token or external tile service. The existing SVG map remains an explicit fallback if MapLibre initialization fails, and the UI labels which runtime is active.

## Infrastructure importer

The importer is `python -m app.infrastructure_import`. It accepts exactly one `--file` or `--url`, one source key (`bts_ports` or `fra_rail`), and bounded `--batch-size`/`--timeout` values. It accepts GeoJSON FeatureCollections (and the common ArcGIS `attributes`/`paths`/`rings` shape), validates WGS84 Point/LineString/Polygon geometry, rejects missing stable IDs, skips malformed records, and logs structured skip/batch messages. It stores raw payloads before canonical assets, uses source-scoped identity plus SHA-256 payload hashes for retries, updates existing assets, and prints JSON stats.

Use the checked-in fixtures for tests only:

```powershell
cd apps/api
python -m app.infrastructure_import --source bts_ports --file app/fixtures/infrastructure_ports.geojson
python -m app.infrastructure_import --source fra_rail --file app/fixtures/infrastructure_rail.geojson
```

Live imports require a public GeoJSON export URL or a downloaded file from the source pages. No credentials are required or accepted by the importer. Do not describe fixtures as full coverage.

## Verification commands

```powershell
cd apps/api
python -m pytest -q
python -m ruff check app tests

cd ..\web
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```
