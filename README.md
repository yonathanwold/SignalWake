# SIGNALWAKE

SIGNALWAKE is a real-time geospatial event intelligence foundation. It turns authoritative National Weather Service alerts and USGS earthquake observations into one canonical event model, then serves that model to a map-first web interface. The long-term platform direction includes infrastructure dependencies, disruptions, simulations, and historical changes; this first slice does not claim those future capabilities.

The first slice is intentionally honest about its boundary:

- `LIVE` means a successful startup fetch, normalization, and persistence pass from NWS or USGS.
- `DEMO` means deterministic fixture data used only when startup ingestion is disabled, a source has no usable live events, or the browser cannot reach the API.
- `DERIVED` means normalized fields such as severity, type, and provenance; it does not mean an infrastructure impact prediction.
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
