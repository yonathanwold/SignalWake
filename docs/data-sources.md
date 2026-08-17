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
