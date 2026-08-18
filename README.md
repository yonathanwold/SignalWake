# SIGNALWAKE

SIGNALWAKE is a real-time geospatial event intelligence foundation. It turns authoritative National Weather Service alerts and USGS earthquake observations into one canonical event model, then serves that model to a map-first web interface. Phase 2 adds persistent infrastructure reference data from public U.S. transportation datasets. Reference geometry is searchable and inspectable; it is not a disruption score, dependency graph, or impact prediction.

The first slice is intentionally honest about its boundary:

- `LIVE` means a successful startup fetch, normalization, and persistence pass from NWS or USGS.
- `DEMO` means deterministic fixture data used only when startup ingestion is disabled, a source has no usable live events, or the browser cannot reach the API.
- `DERIVED` means normalized event fields such as severity and type; it does not mean an infrastructure impact prediction.
- `REFERENCE` means an imported infrastructure asset whose geometry and metadata came from a named public source. It is intentionally separate from live event observations.
- Infrastructure Graph is a bounded, API-backed workspace over persisted Phase 3 relationships. Scenario Lab is a separate second-order graph comparison surface; Historical Replay, Source Provenance, and System Health remain routed shells for later milestones.
- Phase 4 assessments are a separate `SIGNALWAKE DERIVED ASSESSMENT` layer. They correlate an event with source-provided infrastructure using deterministic geometry predicates, bounded radius checks, and bounded structural graph traversal. They are exposure-prioritization scores, not outage, economic-loss, causal, or operational dependency predictions.
- The Operational Map uses MapLibre GL JS with local, token-free GeoJSON rendering for the same canonical events as the feed; its SVG surface is an explicit runtime fallback only if MapLibre initialization fails.

## Run locally

1. Copy `.env.example` to `.env` and adjust values if needed.
2. Start the API:

   ```powershell
   cd apps/api
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -e ".[dev]"
   uvicorn app.main:app --reload --port 8000
   ```

3. In another terminal start the web app:

   ```powershell
   cd apps/web
   npm.cmd install
   npm.cmd run dev
   ```

Open `http://localhost:3000`. By default the API performs one bounded real fetch from both authoritative sources during startup. With `USE_DEMO_DATA=true`, fixtures are used only per source when that live pass is unavailable or produces no usable events; set it to `false` to run without fixture fallback. The browser also falls back to clearly labeled deterministic demo events when it cannot reach the API.

### Import infrastructure reference data

Infrastructure is deliberately imported as a bounded batch instead of silently fetched at API startup. From `apps/api`, import a downloaded GeoJSON FeatureCollection (or a public GeoJSON URL):

```powershell
python -m app.infrastructure_import --source bts_ports --file app/fixtures/infrastructure_ports.geojson
python -m app.infrastructure_import --source fra_rail --file app/fixtures/infrastructure_rail.geojson
python -m app.infrastructure_import --source bts_ports --url <public-geojson-export-url> --batch-size 250
```

Each command prints JSON import stats (`fetched_count`, `inserted_count`, `updated_count`, `skipped_count`, and `duplicate_count`). The checked-in files are small representative test fixtures, not the full live datasets. Source landing pages, export guidance, and attribution are in [docs/data-sources.md](docs/data-sources.md).

### Build the infrastructure graph

After importing one or both Phase 2 datasets, explicitly rebuild deterministic derived relationships:

```powershell
python -m app.derivation
```

The builder creates only `CONNECTED_TO` (rail LineString endpoints within 100 m), `INTERSECTS` (actual geometry intersection), and `ADJACENT_TO` (a port point within 25 km of a rail corridor, with matching regions when both are supplied). Distances are WGS84 great-circle/segment estimates in SQLite and PostGIS spatial predicates in production. Edges are `DERIVED`, carry source record/provenance evidence, and are idempotent; stale derived edges are removed without touching future `SOURCE_OBSERVED` edges. No `DEPENDS_ON`, `SUPPLIES`, `ALTERNATIVE_TO`, or impact/scenario edges are inferred.

The graph API is bounded: `/graph/nodes`, `/graph/nodes/{id}`, `/graph/nodes/{id}/neighbors`, `/graph/paths`, `/graph/subgraph`, `/graph/metrics`, and explicit `POST /graph/rebuild` expose sorted nodes, edges, provenance, and structural metrics. The browser workspace defaults to a depth-2 / 30-node subgraph and shows an honest empty state when no persisted edge exists.

### Run a second-order scenario

Scenario Lab creates a persisted definition and then runs it explicitly over a
snapshot of the current graph. `ASSET_UNAVAILABLE` removes one node in memory,
`EDGE_UNAVAILABLE` removes one relationship, and
`MULTIPLE_ASSETS_UNAVAILABLE` removes two or more nodes. The source-backed
assets and relationship rows are never modified. The API is available at
`POST /scenarios`, `GET /scenarios`, `GET /scenarios/{id}`,
`POST /scenarios/{id}/runs`, `GET /scenario-runs/{id}`, and bounded
`GET /scenario-runs/{id}/graph`. Results include baseline/modified hashes,
component and reachability changes, changed bounded shortest paths, alternate
route preservation, articulation consequences, and the transparent
`second-order-v1` resilience formula. See [docs/scenarios.md](docs/scenarios.md)
for the algorithm, limits, and explicit non-claims.

### Recompute event assessments

Assessments are recomputed explicitly for one event. This writes only the
versioned assessment projection and removes stale rows for that event and
methodology; it does not rewrite events, infrastructure facts, or graph edges:

```powershell
python -m app.assessments --event-id <event-id> --radius-km 50 --depth 2
```

The equivalent API call is `POST /assessments/recompute` with JSON such as
`{"event_id":"<event-id>","radius_km":50,"depth":2}`. Read results through
`GET /assessments`, `GET /assessments/{id}`,
`GET /events/{id}/assessments`, and
`GET /infrastructure/{id}/assessments`. The current methodology is
`phase4-v1`: `score = event severity × 0.50 + spatial match × 0.35 + bounded
graph exposure × 0.15`, with each named component and fixed weight persisted
in `score_components`. Confidence is `null` because the available facts do
not support a probability of outage or impact.

## Verification

```powershell
cd apps/api
pytest
ruff check .

cd ..\web
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run build
```

Docker Compose describes the production-shaped Postgres/PostGIS service, but local verification does not require Docker. SQLite is used only for deterministic tests and demo development; the production migration keeps geography in PostGIS geometry columns with GiST indexes.

See [docs/architecture.md](docs/architecture.md), [docs/development.md](docs/development.md), and [docs/data-sources.md](docs/data-sources.md).
