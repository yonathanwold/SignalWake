# SIGNALWAKE architecture

## Vertical slice

```text
NWS / USGS
    | async source adapters (timeout + retry + malformed payload handling)
    v
RawObservation (immutable payload + hash + source record id)
    | deterministic normalizer
    v
Event (canonical schema + provenance + geometry + classification)
    | repository / SQLAlchemy
    v
FastAPI /events, /sources, /health
    | typed JSON contract
    v
Next.js Operational Map + Event Feed
```

Each adapter implements the same `SourceAdapter` protocol. Fetching is separate from normalization, and raw payloads are preserved before canonical events are written. Payload hashes and source-scoped record IDs make retries idempotent. A normalization version is stored with every event so later schema changes can be replayed safely.

## Persistence

The runtime defaults to SQLite for an immediately usable portfolio demo and deterministic tests. PostgreSQL + PostGIS is the target deployment model. `apps/api/migrations/001_initial.sql` defines `geometry geometry(Geometry, 4326)`, a GiST index, and a bounding-box intersection query shape using `ST_Intersects` and `ST_MakeEnvelope`.

The SQLAlchemy model stores a serialized GeoJSON geometry for SQLite compatibility and keeps latitude/longitude as indexed scalar fields for the test path. A PostGIS migration can materialize the geometry column without changing the API contract.

## API contract

- `GET /health` — service, database, and source freshness status.
- `GET /sources` — source registry with latest fetch status and freshness.
- `GET /events` — latest-first events with `bbox`, `source`, `type`, `severity`, `start_time`, `end_time`, `limit`, `cursor`, and `page` filters.
- `GET /events/{id}` — event detail including provenance and raw observation reference.

The browser's map markers and feed rows are both projections of the same `Event` response. There is no second static map dataset.

