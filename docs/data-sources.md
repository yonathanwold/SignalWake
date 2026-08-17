# Authoritative data sources

## National Weather Service

- Endpoint: `https://api.weather.gov/alerts/active?status=actual`
- Format: GeoJSON FeatureCollection.
- Record identity: NWS alert `id` or `properties.id`.
- Geometry: alert polygon when provided; point fallback from `geocode` is not fabricated.
- Terms: NWS requests require a descriptive `User-Agent`; configure it through `SOURCE_USER_AGENT`.

## United States Geological Survey

- Endpoint: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson`
- Format: GeoJSON FeatureCollection.
- Record identity: feature `id`.
- Geometry: GeoJSON Point `[longitude, latitude, depth]`.
- Magnitude: normalized to deterministic severity bands for the interface.

## Startup ingestion behavior

When `INGEST_ON_STARTUP=true` (the default), the API runs one bounded fetch/normalize/persist pass for NWS and USGS during startup. Each source records `last_attempt_at`, `last_success_at`, `last_http_status`, `last_error`, and `freshness_seconds`. Valid features become `LIVE` canonical events with their raw payload and provenance; malformed features are logged and skipped while the remaining features continue.

The pass is idempotent by source-scoped record identity and payload hash. `USE_DEMO_DATA=true` is only a fallback: fixture rows are seeded for a source when its live fetch fails or produces no usable events, and never replace a source that produced successful `LIVE` events. No permanent queue or scheduler is included in Phase 1; a later worker can call the same service boundary. The API never fabricates freshness: unavailable values are represented as `null`/`UNKNOWN`, and a source error is surfaced as `ERROR`.

## Infrastructure reference sources

Phase 2 uses two separate public U.S. Department of Transportation datasets. They are imported as `REFERENCE` assets, not as live observations:

### BTS Port Facilities

- Dataset page: [BTS Port Facilities](https://data-usdot.opendata.arcgis.com/datasets/usdot::port-facilities/about)
- Publisher: U.S. Department of Transportation, Bureau of Transportation Statistics.
- Useful fields: stable facility/object ID, port/facility name, facility type, state/region, and geometry. Operator/owner/status are retained only when supplied.
- Attribution: identify BTS and link to the dataset page in downstream use.
- Licensing: U.S. Government public data; review the current dataset page and export terms before redistribution. SIGNALWAKE does not claim a separate license for the source data.

### FRA Rail Lines

- Dataset page: [FRA Rail Lines](https://data-usdot.opendata.arcgis.com/datasets/usdot::rail-lines/about)
- Publisher: U.S. Department of Transportation, Federal Railroad Administration.
- Useful fields: stable line/object ID, railroad or route name, subdivision/type, state/region, status when supplied, and LineString geometry.
- Attribution: identify FRA and link to the dataset page in downstream use.
- Licensing: U.S. Government public data; review the current dataset page and export terms before redistribution. SIGNALWAKE does not claim a separate license for the source data.

The source URLs above are authoritative landing pages. The importer accepts a downloaded GeoJSON export or a caller-supplied URL that returns GeoJSON; it does not scrape HTML landing pages or silently fetch an unbounded national dataset. The checked-in `infrastructure_ports.geojson` and `infrastructure_rail.geojson` files are representative fixtures for deterministic tests only.

## Infrastructure import provenance

Every asset retains its source key and stable source record ID, source URL/name, attribution, license note, fetch time, adapter version, payload hash, and raw record ID. Changed source payloads update the canonical asset by `(source_id, source_asset_id)`; repeated payloads do not create duplicate raw or asset rows. `source_updated_at` is null when the source does not supply an update value. Reference data has no live freshness health badge because it is a caller-triggered batch import.

## Graph relationships and provenance

The graph uses only the imported BTS port points and FRA rail LineStrings. It
does not treat proximity as a generic dependency signal. An explicit rebuild
(`python -m app.derivation`, or `POST /graph/rebuild`) applies these rules:

| Edge | Deterministic rule | Evidence |
| --- | --- | --- |
| `CONNECTED_TO` | Rail LineString endpoints within 100 m (default) | endpoint predicate, tolerance, measured distance, both asset/source records |
| `INTERSECTS` | Actual supported geometry intersection not represented by endpoint connectivity | intersection predicate and endpoint check |
| `ADJACENT_TO` | Port Point to rail corridor within 25 km (default); both supplied regions must match | distance predicate, measured distance, threshold, region check |

Distances use WGS84 great-circle/segment calculations in SQLite and PostGIS
geography predicates in production. Every generated edge is labeled
`DERIVED`, includes the derivation method/version and source URLs/record IDs in
evidence, and uses undirected semantics. The relationship table can retain
future `SOURCE_OBSERVED` rows with source relationship IDs; derived rebuilds
never overwrite or delete those rows. No `DEPENDS_ON`, `SUPPLIES`,
`ALTERNATIVE_TO`, or `LOCATED_IN` edge is currently supported, and graph edges
are not event impact assessments.
