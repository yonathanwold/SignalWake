# Historical Replay

Historical Replay answers a narrow question: **what did SIGNALWAKE know at
this exact time?** It does not rewrite an event's source timestamps to make a
later view look like an earlier one.

## Two clocks

Every replayable record keeps two separate clocks:

- **Event time** is supplied by the source (`observed_at`, `effective_at`, and
  `expires_at`). It describes when the source says an event happened or was
  valid.
- **Knowledge time** is when SIGNALWAKE recorded the observation or generated
  a derived result. Event versions use `received_at`/`fetched_at`, imported
  asset versions use the import time, assessment versions use their generated
  time, and source snapshots use the ingest attempt time.

An event can therefore have an event time before a replay boundary but still
be absent because it arrived late. A replay includes a version only when its
knowledge time is at or before `at` (the boundary is inclusive). The response
keeps `event_time`, `knowledge_at`, `happened_by_at`, and `temporal_status`
together so “known by then” is not confused with “happened by then.”

For event validity, `effective_at <= at` is the inclusive start and
`at >= expires_at` is expired. An event known before its effective time is
labeled `historical`; source-observed events remain distinguishable from the
source `status` field. Expiration does not remove the version from history.

## Version tables and late arrivals

The live `Event`, `InfrastructureAsset`, `Source`, and
`InfrastructureAssessment` rows remain current projections for existing API
clients. Phase 6 adds append-only snapshots:

- `event_versions` keyed by stable `source_id + source_event_id` and payload
  hash;
- `infrastructure_asset_versions` keyed by stable source asset identity and
  payload hash;
- `infrastructure_assessment_versions` keyed by methodology-versioned
  assessment key, including tombstones when recompute removes a current row;
- `source_state_versions` and `infrastructure_source_versions` for ingest and
  import freshness state.

Each event, asset, and assessment version has a recorded/generated timestamp
and a maintained `valid_to` equal to the next version's knowledge timestamp.
Repeated polling of an identical payload is idempotent; a changed payload,
late arrival, or recompute creates a new snapshot. Existing raw payloads stay
immutable.

## APIs and bounds

All replay timestamps must be timezone-aware. UTC (`Z`) is recommended; naive
or ambiguous timestamps are rejected with HTTP 422. Responses normalize
timestamps to UTC. Every endpoint is bounded to 100 returned records per
collection/change list, and internal history scans are capped at 10,000 rows;
`truncated` is true when a bound was reached.

- `GET /replay/timeline?start_time=&end_time=&limit=` returns deterministic,
  time-ordered markers for event, assessment, asset, and source state changes.
- `GET /replay/state?at=&limit=` returns an as-of projection of events,
  assessments, infrastructure, and source states. It does not download the
  raw payload history.
- `GET /replay/compare?from_time=&to_time=&limit=` returns bounded A/B change
  lists: newly known, updated, and expired events; new/changed assessments;
  and newly exposed/changed infrastructure.

The web `/replay` workspace fetches the state again when the scrubber moves,
shows UTC timestamps and knowledge/event-time fields, and never substitutes
the live dashboard's demo fixtures. If the API has no recorded history it
shows **No historical replay data available**.

## Limitations

Replay covers the event, imported reference-asset, assessment, and source
state projections. It does not reconstruct unversioned graph relationship
rows or scenario runs; those remain current/explicit Phase 3–5 projections.
Historical coverage begins when Phase 6 version rows are written, so an old
database needs a controlled backfill if older replay is required. SQLite
tests exercise the semantics deterministically; PostgreSQL migrations use
the same append-only tables and indexes.
