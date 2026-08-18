-- Phase 5 deterministic second-order scenario projection.
-- These tables retain scenario inputs and graph snapshots. They never mutate
-- infrastructure assets or persisted relationship rows.
CREATE TABLE IF NOT EXISTS scenarios (
  id uuid PRIMARY KEY,
  name text NOT NULL,
  scenario_type text NOT NULL,
  created_by text NOT NULL,
  assumption text NOT NULL,
  duration_seconds integer,
  methodology_version text NOT NULL,
  input_hash text NOT NULL,
  baseline_graph_hash text NOT NULL,
  baseline_node_count integer NOT NULL,
  baseline_edge_count integer NOT NULL,
  baseline_snapshot_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  assumptions_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT scenario_type_supported CHECK (scenario_type IN ('ASSET_UNAVAILABLE', 'EDGE_UNAVAILABLE', 'MULTIPLE_ASSETS_UNAVAILABLE')),
  CONSTRAINT scenario_duration_nonnegative CHECK (duration_seconds IS NULL OR duration_seconds >= 0)
);
CREATE INDEX IF NOT EXISTS ix_scenario_type_created ON scenarios (scenario_type, created_at);
CREATE INDEX IF NOT EXISTS ix_scenario_methodology ON scenarios (methodology_version);
CREATE INDEX IF NOT EXISTS ix_scenario_baseline_hash ON scenarios (baseline_graph_hash);

CREATE TABLE IF NOT EXISTS scenario_targets (
  id uuid PRIMARY KEY,
  scenario_id uuid NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
  target_kind text NOT NULL,
  target_id uuid NOT NULL,
  position integer NOT NULL,
  target_snapshot_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT scenario_target_kind_supported CHECK (target_kind IN ('NODE', 'EDGE')),
  UNIQUE (scenario_id, target_kind, target_id)
);
CREATE INDEX IF NOT EXISTS ix_scenario_target_lookup ON scenario_targets (target_kind, target_id);

CREATE TABLE IF NOT EXISTS scenario_runs (
  id uuid PRIMARY KEY,
  scenario_id uuid NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
  run_key text NOT NULL UNIQUE,
  status text NOT NULL,
  methodology_version text NOT NULL,
  baseline_graph_hash text NOT NULL,
  modified_graph_hash text NOT NULL,
  started_at timestamptz NOT NULL,
  completed_at timestamptz NOT NULL,
  reproducibility_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL,
  CONSTRAINT scenario_run_status_supported CHECK (status IN ('completed', 'failed'))
);
CREATE INDEX IF NOT EXISTS ix_scenario_run_scenario_created ON scenario_runs (scenario_id, created_at);
CREATE INDEX IF NOT EXISTS ix_scenario_run_status ON scenario_runs (status);

CREATE TABLE IF NOT EXISTS scenario_results (
  id uuid PRIMARY KEY,
  run_id uuid NOT NULL REFERENCES scenario_runs(id) ON DELETE CASCADE UNIQUE,
  baseline_snapshot_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  modified_snapshot_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  metrics_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL
);
