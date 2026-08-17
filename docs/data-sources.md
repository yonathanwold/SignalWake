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

Production ingestion should schedule each adapter independently, retain failed fetch metadata, and alert on freshness degradation. The API never fabricates freshness: unavailable values are represented as `null`/`UNKNOWN`.

