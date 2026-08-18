# Authoritative data sources

## Operational time contract

Operational/live event views use a durable UTC window of the past 48 hours.
`GET /events` defaults to that window and accepts an explicit `start_time` /
`end_time` range only when it is at most 48 hours. An event is included when
its observed, effective, or received timestamp falls in the window, or when a
source-supplied effective/expires validity interval overlaps it. This is a
query boundary only: raw observations and append-only history are never
deleted. Reference assets, static tiles, and replay routes are not silently
converted into live events.

## National Weather Service

- Endpoint: `https://api.weather.gov/alerts/active?status=actual`
- Format: GeoJSON FeatureCollection.
- Record identity: NWS alert `id` or `properties.id`.
- Geometry: alert polygon when provided; point fallback from `geocode` is not fabricated.
- Terms: NWS requests require a descriptive `User-Agent`; configure it through `SOURCE_USER_AGENT`.

### Latest station observations

- Endpoint: `https://api.weather.gov/observations?limit=500`
- Format: GeoJSON FeatureCollection, bounded to 500 provider features.
- Record identity: provider feature `id`.
- Geometry: provider-supplied station Point only; no station coordinates are inferred.
- Fields: station identifier, provider observation timestamp, text description,
  and temperature when supplied. These normalize as `weather_observation`
  events under source key `nws_observations`.

## United States Geological Survey

- Endpoint: `https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson`
- Format: GeoJSON FeatureCollection.
- Record identity: feature `id`.
- Geometry: GeoJSON Point `[longitude, latitude, depth]`.
- Magnitude: normalized to deterministic severity bands for the interface.
- Coverage: rolling past-day summary feed; this is a bounded live window, not an unbounded history download.

## Additional connected near-real-time adapters

- **USGS water services** — a bounded state fan-out (default:
  `VA,CA,TX,WA,FL,NY,PA,OH,IL,CO,AZ,NC`; maximum 25 states and 1,000 rows) is
  normalized to point observations (`water_level_observation`) using gauge
  coordinates and provider timestamps. The adapter records a source error
  instead of returning invented gauge locations.
- **National Hurricane Center** — `CurrentStorms.json` is parsed when the
  public endpoint returns its active-storm list. Only provider-supplied
  positions and timestamps become `tropical_system` events; malformed or empty
  responses are an honest source error/empty run.
- **NOAA CO-OPS** — public station metadata plus latest `water_level` readings.
  Startup uses a capped metadata subset (maximum 25 stations), or explicitly
  configured `NOAA_COOPS_STATION_IDS`; station coordinates always come from the
  metadata response.

## Credentialed live adapters

- **NASA FIRMS** — a real VIIRS NRT area CSV request is enabled only with
  `FIRMS_MAP_KEY`. Requests are bounded to `FIRMS_AREA`, `FIRMS_PRODUCT`, at
  most two days, and 1,000 detections. Without a key the catalog remains
  `REQUIRES_CREDENTIALS` and the layer is empty.
- **AirNow** — a real JSON request is enabled only with `AIRNOW_API_KEY`.
  Requests are bounded to `AIRNOW_BBOX`, `AIRNOW_PARAMETERS`, 48 hours, and
  1,000 observations. Without a key no request is made and the catalog remains
  `REQUIRES_CREDENTIALS`.

NWS alerts, NWS station observations, USGS earthquakes, USGS water, NHC systems,
NOAA CO-OPS, and configured FIRMS/AirNow adapters are persisted through
the same idempotent raw-observation/event path. Startup still performs one
bounded pass; it is not a scheduler.

## Source and layer catalog

`GET /sources/catalog` (also `GET /layers`) is the metadata registry for the
broader operational map. It includes NWS forecasts/observations/storm reports,
NASA FIRMS, AirNow, NOAA CO-OPS, BTS/FRA, FAA, energy, dams, hospitals,
shelters/public safety, MRMS, lightning, snow/temperature, drought/soil,
land/elevation, watersheds/hydrography, Census, FEMA NRI/declarations, social
vulnerability, and CDC wastewater. Every row states its geometry/data kind,
source URL, temporal semantics, adapter version, refresh/counts, and one of
`LIVE`, `NEAR_REAL_TIME`, `REFERENCE`, `REQUIRES_CREDENTIALS`,
`NOT_CONNECTED`, `DEGRADED`, or `ERROR`.

`GET /layers/{key}/data?limit=...` is bounded to 1,000 features and returns
GeoJSON-like source geometry, freshness/provenance, and the same 48-hour
metadata. Credentialed, unconnected, and reference-only layers return an empty
feature list with their status; SIGNALWAKE never emits placeholder dots or
fake records. Large national datasets are represented as catalog/reference or
tile metadata rather than downloaded into the browser.

## Startup ingestion behavior

When `INGEST_ON_STARTUP=true` (the default), the API runs one bounded fetch/normalize/persist pass for NWS alerts, NWS station observations, USGS earthquakes, bounded USGS water states, NHC, and NOAA CO-OPS. FIRMS and AirNow join the pass only when their real credentials are configured. Each source records `last_attempt_at`, `last_success_at`, `last_http_status`, `last_error`, and `freshness_seconds`. Valid features become `LIVE` canonical events with their raw payload and provenance; malformed features are logged and skipped while the remaining features continue.

The web map requests `/events?limit=1000`, matching the API's maximum event page size so the complete bounded source window can render without requesting unbounded history. Point features use a MapLibre cluster source at national zoom; the underlying source coordinates remain unchanged when a cluster expands.

The pass is idempotent by source-scoped record identity and payload hash. `USE_DEMO_DATA=true` is only a fallback for the NWS/USGS deterministic fixtures: fixture rows are seeded for a source when its live fetch fails or produces no usable events, and never replace a source that produced successful `LIVE` events. No permanent queue or scheduler is included; a later worker can call the same service boundary. The API never fabricates freshness: unavailable values are represented as `null`/`UNKNOWN`, and a source error is surfaced as `ERROR`.

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

### Import safety boundary

The `--file` path is the recommended deterministic/demo path. For `--url`, the
importer requires HTTP(S), resolves and rejects localhost/private/link-local/
reserved/metadata targets, validates each redirect hop, allows at most three
redirects, and bounds the response to 10 MiB and 100,000 features. Timeout is
bounded to 120 seconds. These controls reduce SSRF and accidental giant
downloads; they do not verify that a public dataset is trustworthy or licensed.
Operator errors are sanitized and raw source records are retained only for the
documented provenance contract.

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

## Phase 4 assessment inputs and limits

Assessments use only persisted event observations, imported reference asset
geometry/region fields, and persisted graph relationship evidence. They are
stored separately as `SIGNALWAKE DERIVED ASSESSMENT` rows and are never source
facts. Recompute is explicit (`python -m app.assessments --event-id ...` or
`POST /assessments/recompute`) and bounded by caller-selected radius/depth.

`EVENT_INTERSECTS_INFRASTRUCTURE` uses an inclusive geometry intersection.
`INFRASTRUCTURE_WITHIN_EVENT_RADIUS` applies only when the event is a point and
uses an inclusive WGS84 point-to-asset distance. `DEPENDENCY_EXPOSURE` uses a
bounded traversal through the undirected graph and stores the seed, path,
relationship IDs, and relationship evidence. It is structural connected-graph
exposure, not operational upstream/downstream dependency. A regional
assessment is not emitted unless both the event region and asset region are
actual known facts; no region is inferred from map position or geometry.

The `phase4-v1` prioritization score stores event severity (50%), spatial match
(35%), and bounded graph exposure (15%) components and their fixed weights.
Confidence is `null`: these sources do not provide defensible outage,
consequence, economic-loss, or causal labels. Scores therefore do not predict
impact or service interruption, and Phase 4 does not include Scenario Lab.
SQLite geometry helpers are deterministic fixture tooling; PostGIS and actual
dataset coverage are deployment-dependent.

## Phase 7 retrieval and provenance metadata

Each NWS/USGS ingest pass creates one `TransformationRun` with adapter version,
start/completion status, retrieved/accepted/rejected counts, and any error.
Malformed features are counted as rejected while valid normalized events are
counted as accepted. The corresponding `/sources` item exposes the latest run
ID and counters alongside existing attempt/success/error/HTTP/freshness
fields. `expected_update_interval_seconds` is nullable because no interval is
asserted when one is not supplied by the source or deployment.

Infrastructure imports create the same run record with importer version,
records processed/skipped, and the existing import timestamp/error metadata.
Graph derivation, assessment recomputation, and scenario execution also
record their methodology/derivation versions and bounded counters. These are
processing facts, not source claims.

## Lineage contract

`GET /provenance/lineage?object_type=...&object_id=...` answers where a claim
came from with bounded one-hop edges. Supported focus types are `source`,
`raw_observation`, `event`, `raw_infrastructure_record`, `asset`,
`relationship`, `assessment`, `scenario`, and `scenario_run`; scenario result
and historical version nodes can appear in returned graphs. Direct source and
raw nodes are labeled `direct`; normalized, relationship, assessment, and
scenario nodes are labeled `derived`. Evidence and transformation versions
are surfaced on nodes/edges rather than inferred from labels.

The API derives legacy links from stable IDs and evidence when no explicit
`LineageRecord` exists: raw observation → event, raw infrastructure record →
asset, asset → relationship, event/asset/relationship → assessment, and
scenario → run/result. The optional `at=` boundary includes the latest
knowledge-time event or assessment versions known by that time. Expired
objects remain understandable through append-only version metadata; a
missing current projection is not replaced with invented source data.
