-- Phase 6 append-only knowledge-time snapshots for bounded Historical Replay.
CREATE TABLE IF NOT EXISTS event_versions (
  id uuid PRIMARY KEY,
  event_id uuid NOT NULL REFERENCES events(id),
  source_id uuid NOT NULL REFERENCES sources(id),
  source_event_id text NOT NULL,
  raw_observation_id uuid REFERENCES raw_observations(id),
  recorded_at timestamptz NOT NULL,
  valid_to timestamptz,
  payload_hash text NOT NULL,
  snapshot_json jsonb NOT NULL,
  UNIQUE (event_id, payload_hash)
);
CREATE INDEX IF NOT EXISTS ix_event_version_identity_recorded ON event_versions (source_id, source_event_id, recorded_at);
CREATE INDEX IF NOT EXISTS ix_event_version_recorded ON event_versions (recorded_at);

CREATE TABLE IF NOT EXISTS source_state_versions (
  id uuid PRIMARY KEY,
  source_id uuid NOT NULL REFERENCES sources(id),
  recorded_at timestamptz NOT NULL,
  snapshot_json jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_source_state_source_recorded ON source_state_versions (source_id, recorded_at);
CREATE INDEX IF NOT EXISTS ix_source_state_recorded ON source_state_versions (recorded_at);

CREATE TABLE IF NOT EXISTS infrastructure_source_versions (
  id uuid PRIMARY KEY,
  source_id uuid NOT NULL REFERENCES infrastructure_sources(id),
  recorded_at timestamptz NOT NULL,
  snapshot_json jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_infra_source_state_source_recorded ON infrastructure_source_versions (source_id, recorded_at);
CREATE INDEX IF NOT EXISTS ix_infra_source_state_recorded ON infrastructure_source_versions (recorded_at);

CREATE TABLE IF NOT EXISTS infrastructure_asset_versions (
  id uuid PRIMARY KEY,
  asset_id uuid NOT NULL REFERENCES infrastructure_assets(id),
  source_id uuid NOT NULL REFERENCES infrastructure_sources(id),
  source_asset_id text NOT NULL,
  recorded_at timestamptz NOT NULL,
  valid_to timestamptz,
  payload_hash text NOT NULL,
  snapshot_json jsonb NOT NULL,
  UNIQUE (asset_id, payload_hash)
);
CREATE INDEX IF NOT EXISTS ix_infra_asset_version_identity_recorded ON infrastructure_asset_versions (source_id, source_asset_id, recorded_at);
CREATE INDEX IF NOT EXISTS ix_infra_asset_version_recorded ON infrastructure_asset_versions (recorded_at);

CREATE TABLE IF NOT EXISTS infrastructure_assessment_versions (
  id uuid PRIMARY KEY,
  assessment_id uuid REFERENCES infrastructure_assessments(id),
  assessment_key text NOT NULL,
  event_id uuid NOT NULL REFERENCES events(id),
  methodology_version text NOT NULL,
  generated_at timestamptz NOT NULL,
  valid_to timestamptz,
  is_deleted boolean NOT NULL DEFAULT false,
  snapshot_json jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_assessment_version_key_generated ON infrastructure_assessment_versions (assessment_key, generated_at);
CREATE INDEX IF NOT EXISTS ix_assessment_version_generated ON infrastructure_assessment_versions (generated_at);
