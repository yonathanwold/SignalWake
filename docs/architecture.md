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

Phase 3 adds a separate, persisted graph layer. It is intentionally built
from the two canonical Phase 2 asset types only:

```text
InfrastructureAsset + source/provenance
    | explicit python -m app.derivation or POST /graph/rebuild
    v
InfrastructureRelationship (source-aware, idempotent edge)
    | bounded adjacency + deterministic traversals
    v
/graph/nodes, /graph/nodes/{id}/neighbors, /graph/paths,
/graph/subgraph, /graph/metrics
    v
Infrastructure Graph scoped workspace
```

Phase 4 adds an explicit assessment projection over those two persisted
domains. It does not overwrite either input layer:

```text
LIVE Event + REFERENCE InfrastructureAsset + persisted graph edges
    | explicit event-scoped recompute (bounded radius/depth)
    v
InfrastructureAssessment (SIGNALWAKE DERIVED ASSESSMENT)
    | typed list/detail/event/asset views
    v
Event Feed + Operational Map inspectors + Graph node details
```

Supported assessment types are `EVENT_INTERSECTS_INFRASTRUCTURE` (inclusive
geometry intersection), `INFRASTRUCTURE_WITHIN_EVENT_RADIUS` (inclusive
point-to-asset distance for point-only events), and `DEPENDENCY_EXPOSURE`
(bounded traversal from a directly correlated asset through persisted graph
relationships). Since current graph edges are undirected, the latter means
structural connected-graph exposure, not upstream/downstream dependency or an
outage. `REGIONAL_INFRASTRUCTURE_EXPOSURE` is reserved for a future event
region fact and is not emitted when the source event does not actually provide
one; geometry never invents a region.

`InfrastructureAssessment` is a separate persisted derived layer with a
stable methodology-versioned key, event/asset foreign keys, optional region,
severity/status, score, nullable confidence, JSON evidence/components/metadata,
and timestamps. `phase4-v1` stores this transparent formula and fixed weights
for every row:

```text
score = event_severity_score * 0.50
      + spatial_match_score * 0.35
      + graph_exposure_score * 0.15
```

Severity normalizes `info=.2`, `advisory=.4`, `watch=.6`, `warning=.8`, and
`critical=1.0`. Intersection has a 100 spatial match; radius uses
`max(0, 1 - distance/radius) × 100`; graph exposure uses bounded hop
proximity. The score is exposure prioritization only, not predicted impact.
Confidence is `null` because available facts do not support a probability of
outage or consequence. Recompute upserts stable keys and removes stale rows
only for the selected event and methodology.

Phase 5 adds a separate Scenario Lab projection. It snapshots the current
graph, records explicit node/edge targets, and compares an in-memory modified
graph without mutating assets or relationship rows:

```text
REFERENCE assets + persisted graph edges
    | POST /scenarios (validate targets + snapshot baseline)
    v
Scenario + ScenarioTarget
    | POST /scenarios/{id}/runs (deterministic in-memory removals)
    v
ScenarioRun + ScenarioResult (baseline/modified hashes, metrics, evidence)
    | GET /scenario-runs/{id}/graph
    v
Scenario Lab baseline / removed / affected / derived-second-order views
```

The supported mutations are one asset, one relationship, or multiple assets.
The graph remains undirected; results use components, bounded BFS shortest
paths, alternate-route checks, and Tarjan articulation points. The
`second-order-v1` score is a transparent structural comparison and never an
outage, service, economic, logistical, or causal prediction. Full assumptions,
formula, safe bounds, and reproducibility rules are in `docs/scenarios.md`.

Current node types are `port` (BTS Port Facilities) and `rail_corridor` (FRA
Rail Lines). Current relationship types are:

- `CONNECTED_TO`: two rail LineString endpoints are within the default 100 m
  endpoint tolerance. This is endpoint topology, not generic proximity.
- `INTERSECTS`: supported geometries have an actual segment/point intersection
  and the pair is not represented by endpoint connectivity.
- `ADJACENT_TO`: a port Point is within the default 25 km measured distance of
  a rail corridor. When both assets provide a region, the normalized regions
  must match. Evidence records the measured distance and threshold.

All generated edges are `DERIVED`, use undirected semantics, and retain both
asset IDs, source-scoped record IDs, source URLs, geometry predicate, rule,
version, and applicable tolerance/distance in JSON evidence. The schema also
supports `SOURCE_OBSERVED` edges and source relationship IDs; the derived
rebuild never deletes or updates those rows. Unsupported `DEPENDS_ON`,
`SUPPLIES`, `ALTERNATIVE_TO`, and `LOCATED_IN` semantics are not generated.

Each adapter implements the same `SourceAdapter` protocol. Fetching is separate from normalization, and raw payloads are preserved before canonical events are written. Payload hashes and source-scoped record IDs make retries idempotent. A normalization version is stored with every event so later schema changes can be replayed safely.

## Persistence

The runtime defaults to SQLite for an immediately usable portfolio demo and deterministic tests. PostgreSQL + PostGIS is the target deployment model. `apps/api/migrations/001_initial.sql` defines `geometry geometry(Geometry, 4326)`, a GiST index, and a bounding-box intersection query shape using `ST_Intersects` and `ST_MakeEnvelope`.

The Phase 2 model uses `InfrastructureSource`, `RawInfrastructureRecord`, and `InfrastructureAsset`. Assets have a source-scoped stable ID, name/type/subtype, optional operator/owner/status, region, source-updated/imported/updated timestamps, metadata, classification, and provenance. `geometry_geojson` supports deterministic SQLite tests; production migration `002_infrastructure.sql` adds `geometry geometry(Geometry, 4326)` with a GiST index. The importer populates that PostGIS geometry with `ST_GeomFromGeoJSON` when the PostgreSQL dialect is active.

The migration also adds source/type/region indexes and unique `(source_id, source_asset_id)` identity. Raw payloads are unique by `(source_id, payload_hash)`, while changed payloads for the same source record update one canonical asset and preserve the latest raw record link.

`003_infrastructure_relationships.sql` stores the stable relationship key,
endpoint foreign keys, relationship/source/directionality fields, derivation
method/version, optional confidence, evidence JSON, distance/tolerance, and
timestamps. Endpoint/type/source indexes support bounded adjacency lookups.

`004_infrastructure_assessments.sql` stores the separate assessment projection
with event/asset foreign keys, stable-key uniqueness, score/confidence checks,
and event/type/asset/status/methodology indexes. JSON evidence/components are
validated by the typed API and retain predicates, distances/radii, graph paths,
relationship IDs, formula/weights, and source fact IDs.

`005_scenarios.sql` stores scenario definitions, explicit node/edge target
rows, deterministic run keys, and baseline/modified result snapshots. Scenario
tables are a derived projection and do not own or mutate infrastructure facts
or persisted graph relationships.

## API contract

- `GET /health` — service, database, and source freshness status.
- `GET /sources` — source registry with latest fetch status and freshness.
- `GET /events` — latest-first events with `bbox`, `source`, `type`, `severity`, `start_time`, `end_time`, `limit`, `cursor`, and `page` filters.
- `GET /events/{id}` — event detail including provenance and raw observation reference.
- `GET /infrastructure` — bounded reference assets with `bbox`, `type`, `source`, `region`, `limit`, `cursor`, and `page` filters.
- `GET /infrastructure/{id}` — one reference asset with geometry, source attribution/license, timestamps, and provenance.
- `GET /graph/nodes` — bounded/paginated graph nodes with type, region, source, and structural metric filters.
- `GET /graph/nodes/{id}` — one asset plus graph metrics.
- `GET /graph/edges` — bounded relationship choices for graph/scenario views.
- `GET /graph/nodes/{id}/neighbors` — bounded depth traversal; current edges are undirected, so `direction=in/out` is rejected.
- `GET /graph/paths` — shortest path within a caller-supplied hop bound; missing nodes and no-path cases are 404.
- `GET /graph/subgraph` — bounded root/depth/type/region/relationship subgraph.
- `GET /graph/metrics` — structural metrics for one node or a bounded filtered set.
- `POST /graph/rebuild` — explicit bounded derivation with configurable endpoint tolerance and port-to-rail distance.
- `GET /assessments` — bounded list with event, asset, type, status, score range, and cursor filters.
- `GET /assessments/{id}` — one derived assessment with evidence and named score components.
- `GET /events/{id}/assessments` and `GET /infrastructure/{id}/assessments` — scoped assessment views.
- `POST /assessments/recompute` — explicit event-scoped upsert/cleanup with validated radius, depth, and asset bounds.
- `POST /scenarios` — validate targets and persist a baseline graph snapshot.
- `GET /scenarios`, `GET /scenarios/{id}` — side-effect-free scenario definitions.
- `POST /scenarios/{id}/runs` — explicit deterministic in-memory graph mutation and persisted result; repeated calls are idempotent for the same input/baseline/methodology.
- `GET /scenario-runs/{id}`, `GET /scenario-runs/{id}/result` — run evidence, metrics, hashes, and formula components.
- `GET /scenario-runs/{id}/graph?state=baseline|modified` — bounded graph snapshot for visualization.

The browser's map markers and feed rows are both projections of the same `Event` response. Infrastructure layers and the reference inspector are projections of `/infrastructure`; the browser does not ship a full static dataset. MapLibre uses separate GeoJSON sources for events and infrastructure. The SVG renderer remains a fallback.

## Spatial behavior and limits

PostgreSQL uses `ST_Intersects(geometry, ST_MakeEnvelope(..., 4326))` for viewport filtering and `ST_DWithin(geometry::geography, ..., metres)` for distance queries. Reusable service functions also expose geometry intersection and distance operations for internal workflows. SQLite has no spatial extension in the deterministic test path, so it validates Point/LineString/Polygon GeoJSON and filters a bounded in-memory candidate set with conservative pure-Python primitives. It is not a production-scale spatial substitute. API limits are capped at 500 assets per request; callers should use `cursor`/`page` for larger imports.

Infrastructure assets are reference facts only. Assessments are deterministic
exposure prioritization, not predicted impact. SIGNALWAKE does not claim
outages, economic losses, real-world operational causality, or
upstream/downstream dependency. Scenario Lab is a separate structural graph
comparison layer; it does not add those semantics.

Assessment recompute is deliberately bounded and event-specific. SQLite uses
the same pure-Python geometry helpers as fixture tests but is not a
production-scale spatial substitute; PostGIS runtime coverage and actual
source dataset coverage depend on deployment and imported data. Missing
geometry, event point coordinates, regions, or relationship evidence produce
no assessment rather than an invented fact.

## Graph engine limits and metrics

The in-memory engine is built per bounded request from persisted relationships.
Adjacency is sorted by stable IDs and relationship type so neighbors, paths,
components, and subgraphs are reproducible. The derivation service uses a
deterministic longitude/latitude candidate grid rather than an unbounded
all-pairs proximity scan; PostgreSQL deployments can use the same geometry
predicates with the indexed PostGIS columns.

Metrics are structural only: `degree`, connected `component_size`, normalized
unweighted Brandes `betweenness_centrality` (0–1), Tarjan
`is_articulation_point`, and `alternate_path_count` (direct neighbors still
reachable after their direct edge is removed). These numbers describe the
bounded persisted relationship graph; they are not reliability, importance,
impact, upstream/downstream, or disruption scores. API limits cap any response
at 200 nodes and subgraphs default to depth 2 / 50 nodes; the browser uses a
depth-2 / 30-node scope.
