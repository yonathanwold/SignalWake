# Source provenance workspace

SIGNALWAKE keeps source facts, normalized projections, and derived claims
separate. Phase 7 makes those boundaries inspectable.

## What is linked

The deterministic lineage flow is:

```text
SOURCE
  -> RAW OBSERVATION / RAW INFRASTRUCTURE RECORD
  -> NORMALIZED EVENT / REFERENCE ASSET
  -> RELATIONSHIP
  -> ASSESSMENT
  -> SCENARIO / SCENARIO RUN / RESULT
```

Raw payload IDs and hashes are direct source-ingest evidence. Events and
assets are normalized projections carrying adapter/import versions. Graph
relationships are derived only from supported geometry rules and retain
predicate, measured distance/tolerance, source IDs, and derivation version.
Assessments retain event/asset/relationship evidence and methodology version.
Scenario runs retain graph snapshots, input hashes, and second-order
methodology metadata. None of the derived layers claims an outage, causal
dependency, or economic impact.

## API

```text
GET /provenance/lineage
  ?object_type=event
  &object_id=<id>
  &direction=upstream|downstream|both
  &limit=50
  [&at=<UTC knowledge boundary>]
```

The response is bounded and includes `nodes`, `edges`, and `truncated`. Nodes
include direct/derived classification, source, observed/ingested/generated
times, transformation/version, freshness when known, confidence when known,
and evidence. Edges include relation kind, timestamps, transformation run
ID, and evidence. Alias paths such as
`/provenance/events/{id}` and `/provenance/assets/{id}` use the same contract.
Unknown IDs return 404; invalid type, direction, or limit returns 422.

`TransformationRun` rows record bounded processing facts for source ingest,
infrastructure import, relationship derivation, assessment recomputation,
and scenario execution. `/sources` keeps these latest counters optional so
existing clients remain compatible. Missing run data, source schedules, or
freshness is represented as null/UNKNOWN.

## Historical limitations

`at=` is a knowledge-time boundary, not source event time. When available,
append-only event and assessment versions are shown as historical lineage
nodes; the mutable current projection is not changed. Infrastructure and
source replay history remains available through Phase 6 snapshot tables. A
historical object that was never recorded cannot be reconstructed, and the
workspace reports that absence rather than fabricating a chain.
