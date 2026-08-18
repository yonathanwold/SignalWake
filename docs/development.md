# Development notes

## Project layout

- `apps/api/app` — FastAPI app, domain models, adapters, importer, repository, and spatial services.
- `apps/api/tests` — fixture-only adapter, infrastructure, spatial, ingestion, and API tests; no external calls.
- `apps/web/app` — Next.js App Router routes.
- `apps/web/components` — shared map, feed, shell, graph, and Scenario Lab UI.
- `apps/web/lib` — canonical frontend types and API/demo data access.
- `infra/docker-compose.yml` — Postgres/PostGIS target service.

## Data classification

Every visible event is marked `LIVE` or `DEMO`, and normalized source fields are marked `DERIVED` in the interface. A demo event is never described as an observed live event. No code path uses an LLM or makes infrastructure-impact claims.

Infrastructure assets are always classified `REFERENCE`. A source record can carry an operator, owner, status, or source-updated value only when the source supplies it; the normalizer does not fill missing domain facts. The browser keeps the event stream and reference layers visually and semantically separate.

Graph relationships are a separate persisted layer. Current nodes are only
`port` and `rail_corridor`; current edges are `CONNECTED_TO`, `INTERSECTS`, and
`ADJACENT_TO`. `SOURCE_OBSERVED` is reserved for a future source relationship
adapter; the Phase 3 builder writes `DERIVED` edges with an explicit rule,
version, threshold/tolerance, measured distance where applicable, asset/source
record IDs, and source URLs. No dependency, supply, alternative, location,
impact, or scenario semantics are inferred.

Assessments are a third, separate persisted layer. `InfrastructureAssessment`
rows are labeled `SIGNALWAKE DERIVED ASSESSMENT` and never replace `LIVE` event
observations, `REFERENCE` assets, or graph edges. Phase 4 supports geometry
intersection, point-event radius correlation, and bounded structural
connected-graph traversal. Regional exposure is omitted unless an event
region is an actual source fact. Current graph relationships are undirected,
so dependency exposure is not upstream/downstream operational dependency.

The `phase4-v1` score persists named components and fixed weights: event
severity 50%, spatial match 35%, and bounded graph exposure 15%. Severity
normalization is `info .2`, `advisory .4`, `watch .6`, `warning .8`, `critical
1.0`; boundary intersections and radius limits are inclusive. The score
prioritizes review of structural exposure and does not predict outage,
economic loss, consequence, or causality. Confidence is returned as `null`.
Evidence includes source event/asset IDs, geometry predicate or distance/radius,
and graph path/relationship IDs. Recompute is explicit and idempotent:

```powershell
python -m app.assessments --event-id <event-id> --radius-km 50 --depth 2
```

The API equivalent is `POST /assessments/recompute`; bounded list/detail and
event/asset views are under `/assessments`, `/events/{id}/assessments`, and
`/infrastructure/{id}/assessments`. Stale rows are deleted only for the
selected event and methodology version. Scenario Lab is a separate Phase 5
projection and does not rewrite this assessment layer.

## Scenario Lab

Scenario definitions and runs live in `app/scenarios.py` and the
`005_scenarios.sql` migration. A scenario snapshots the sorted undirected graph
at creation time, stores ordered node/edge targets, and executes only an
in-memory removal. The explicit POST run is deterministic and idempotent for
the same scenario input, baseline hash, and `second-order-v1` methodology.
Tests use the exact fixture graph engine and imported rail fixtures to verify
single-node, single-edge, multi-node, component, path, alternate-route,
articulation, repeatability, persistence, API validation, and no-mutation
behavior. The score and all structural metrics are explained in
[`docs/scenarios.md`](scenarios.md); they do not represent outage, service,
economic, logistical, or causal predictions.
Scenario creation rejects persisted graphs above 200 nodes with HTTP 422 before
loading the baseline; scenario graph responses use the same 200-node cap and
an 800-edge response bound.

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

After imports, graph derivation is explicit and repeatable:

```powershell
python -m app.derivation
```

Defaults are 100 m for rail endpoint connectivity and 25 km for port-to-rail
adjacency. The service uses a deterministic spatial candidate grid, removes
stale `DERIVED` edges on rebuild, and never modifies `SOURCE_OBSERVED` rows.
The API also exposes the explicit `POST /graph/rebuild` operation with bounded
settings. GET requests never silently rebuild graph state.

After the graph and assets exist, recompute an event assessment explicitly.
No GET request rebuilds assessments. `radius_km` is capped at 500, traversal
depth at 4, and asset candidates at 5,000. SQLite tests are fixture-only and
do not use network services. PostGIS remains the production spatial runtime;
coverage and conclusions depend on the imported source records.

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

Graph tests cover exact small-graph traversals, components, shortest paths,
degree, articulation points, betweenness, bounded subgraphs, derivation
predicates, duplicate/upsert behavior, stale/unsupported negatives, API
filters/bounds, and provenance. SQLite is the deterministic test path; Docker
PostGIS runtime validation is not available in this environment, so migration
tests assert the SRID, GiST, FK, uniqueness, and predicate DDL instead.
Assessment tests additionally cover exact intersection/radius boundaries,
component formula/version math, null confidence, relationship evidence,
bounded graph traversal, idempotent recompute/stale cleanup, and API filter,
detail, and validation behavior. Tests never call NWS, USGS, or public
infrastructure URLs.
