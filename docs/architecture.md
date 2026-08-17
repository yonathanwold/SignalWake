# SIGNALWAKE architecture

## Vertical slices

```text
NWS / USGS
    | bounded startup ingest_once (timeout + retry + source health metadata)
    v
async source adapters (malformed payload handling)
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

Infrastructure follows a separate, repeatable batch path and joins the same map selection plumbing without pretending to be an event:

```text
BTS Port Facilities / FRA Rail Lines
    | local GeoJSON file or caller-supplied public GeoJSON URL
    v
bounded importer (validation + source identity + payload hash)
    v
RawInfrastructureRecord (immutable payload + hash)
    |
    v
InfrastructureAsset (canonical REFERENCE geometry + provenance)
    | repository / spatial query utilities
    v
FastAPI /infrastructure, /infrastructure/{id}
    v
Operational Map reference layers + infrastructure inspector
```

Each adapter implements the same `SourceAdapter` protocol. Fetching is separate from normalization, and raw payloads are preserved before canonical events are written. Payload hashes and source-scoped record IDs make retries idempotent. A normalization version is stored with every event so later schema changes can be replayed safely.

## Persistence

The runtime defaults to SQLite for an immediately usable portfolio demo and deterministic tests. PostgreSQL + PostGIS is the target deployment model. `apps/api/migrations/001_initial.sql` defines `geometry geometry(Geometry, 4326)`, a GiST index, and a bounding-box intersection query shape using `ST_Intersects` and `ST_MakeEnvelope`.

The Phase 2 model uses `InfrastructureSource`, `RawInfrastructureRecord`, and `InfrastructureAsset`. Assets have a source-scoped stable ID, name/type/subtype, optional operator/owner/status, region, source-updated/imported/updated timestamps, metadata, classification, and provenance. `geometry_geojson` supports deterministic SQLite tests; production migration `002_infrastructure.sql` adds `geometry geometry(Geometry, 4326)` with a GiST index. The importer populates that PostGIS geometry with `ST_GeomFromGeoJSON` when the PostgreSQL dialect is active.

The migration also adds source/type/region indexes and unique `(source_id, source_asset_id)` identity. Raw payloads are unique by `(source_id, payload_hash)`, while changed payloads for the same source record update one canonical asset and preserve the latest raw record link.

## API contract

- `GET /health` — service, database, and source freshness status.
- `GET /sources` — source registry with latest fetch status and freshness.
- `GET /events` — latest-first events with `bbox`, `source`, `type`, `severity`, `start_time`, `end_time`, `limit`, `cursor`, and `page` filters.
- `GET /events/{id}` — event detail including provenance and raw observation reference.
- `GET /infrastructure` — bounded reference assets with `bbox`, `type`, `source`, `region`, `limit`, `cursor`, and `page` filters.
- `GET /infrastructure/{id}` — one reference asset with geometry, source attribution/license, timestamps, and provenance.

The browser's map markers and feed rows are both projections of the same `Event` response. Infrastructure layers and the reference inspector are projections of `/infrastructure`; the browser does not ship a full static dataset. MapLibre uses separate GeoJSON sources for events and infrastructure. The SVG renderer remains a fallback.

## Spatial behavior and limits

PostgreSQL uses `ST_Intersects(geometry, ST_MakeEnvelope(..., 4326))` for viewport filtering and `ST_DWithin(geometry::geography, ..., metres)` for distance queries. Reusable service functions also expose geometry intersection and distance operations for internal workflows. SQLite has no spatial extension in the deterministic test path, so it validates Point/LineString/Polygon GeoJSON and filters a bounded in-memory candidate set with conservative pure-Python primitives. It is not a production-scale spatial substitute. API limits are capped at 500 assets per request; callers should use `cursor`/`page` for larger imports.

Infrastructure assets are reference facts only. SIGNALWAKE does not infer graph edges, disruption likelihood, consequence, or scenario results in Phase 2.
