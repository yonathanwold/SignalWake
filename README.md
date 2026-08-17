# SIGNALWAKE

SIGNALWAKE is an operational event intelligence foundation. It turns authoritative National Weather Service alerts and USGS earthquake observations into one canonical event model, then serves that model to a map-first web interface.

The first slice is intentionally honest about its boundary:

- `LIVE` means a successful fetch from NWS or USGS.
- `DEMO` means deterministic fixture data used when the API has no database or the browser cannot reach the API.
- `DERIVED` means normalized fields such as severity, type, and provenance; it does not mean an infrastructure impact prediction.
- Infrastructure Graph, Scenario Lab, Historical Replay, Source Provenance, and System Health are routed shells for later milestones. They do not invent analytics.

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

Open `http://localhost:3000`. The browser will use the API when available and fall back to clearly labeled deterministic demo events when it is not.

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

