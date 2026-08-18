-- Phase 7 bounded source provenance and transformation lineage.
ALTER TABLE sources ADD COLUMN IF NOT EXISTS expected_update_interval_seconds integer;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_run_id uuid;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_records_retrieved integer;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_records_accepted integer;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_records_rejected integer;
ALTER TABLE infrastructure_sources ADD COLUMN IF NOT EXISTS expected_update_interval_seconds integer;
ALTER TABLE infrastructure_sources ADD COLUMN IF NOT EXISTS last_run_id uuid;
ALTER TABLE infrastructure_sources ADD COLUMN IF NOT EXISTS last_records_retrieved integer;
ALTER TABLE infrastructure_sources ADD COLUMN IF NOT EXISTS last_records_accepted integer;
ALTER TABLE infrastructure_sources ADD COLUMN IF NOT EXISTS last_records_rejected integer;

CREATE TABLE IF NOT EXISTS transformation_runs (
  id uuid PRIMARY KEY,
  run_kind text NOT NULL,
  version text NOT NULL,
  source_id uuid,
  started_at timestamptz NOT NULL,
  completed_at timestamptz,
  status text NOT NULL,
  records_retrieved integer,
  records_accepted integer,
  records_rejected integer,
  error text,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_transformation_run_kind_started ON transformation_runs (run_kind, started_at);
CREATE INDEX IF NOT EXISTS ix_transformation_run_source_started ON transformation_runs (source_id, started_at);

CREATE TABLE IF NOT EXISTS lineage_records (
  id uuid PRIMARY KEY,
  upstream_type text NOT NULL,
  upstream_id text NOT NULL,
  downstream_type text NOT NULL,
  downstream_id text NOT NULL,
  relation_kind text NOT NULL,
  transformation_run_id uuid REFERENCES transformation_runs(id),
  evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  observed_at timestamptz,
  ingested_at timestamptz,
  generated_at timestamptz,
  created_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lineage_upstream ON lineage_records (upstream_type, upstream_id);
CREATE INDEX IF NOT EXISTS ix_lineage_downstream ON lineage_records (downstream_type, downstream_id);
CREATE INDEX IF NOT EXISTS ix_lineage_created ON lineage_records (created_at);
