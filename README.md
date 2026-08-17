# SIGNALWAKE

SIGNALWAKE is a real-time geospatial event intelligence foundation. It turns authoritative National Weather Service alerts and USGS earthquake observations into one canonical event model, then serves that model to a map-first web interface. Phase 2 adds persistent infrastructure reference data from public U.S. transportation datasets. Reference geometry is searchable and inspectable; it is not a disruption score, dependency graph, or impact prediction.

The first slice is intentionally honest about its boundary:

- `LIVE` means a successful startup fetch, normalization, and persistence pass from NWS or USGS.
- `DEMO` means deterministic fixture data used only when startup ingestion is disabled, a source has no usable live events, or the browser cannot reach the API.
- `DERIVED` means normalized event fields such as severity and type; it does not mean an infrastructure impact prediction.
- `REFERENCE` means an imported infrastructure asset whose geometry and metadata came from a named public source. It is intentionally separate from live event observations.
- Infrastructure Graph, Scenario Lab, Historical Replay, Source Provenance, and System Health are routed shells for later milestones. They do not invent analytics.
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
