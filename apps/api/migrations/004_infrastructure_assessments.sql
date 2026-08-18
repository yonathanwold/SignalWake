-- Phase 4 deterministic event-to-infrastructure assessment projection.
-- This table is derived only: it never replaces source observations, assets,
-- or persisted infrastructure relationship edges.
CREATE TABLE IF NOT EXISTS infrastructure_assessments (
  id uuid PRIMARY KEY,
  assessment_key text NOT NULL UNIQUE,
  assessment_type text NOT NULL,
  event_id uuid NOT NULL REFERENCES events(id),
  affected_asset_id uuid REFERENCES infrastructure_assets(id),
  affected_region text,
  severity text NOT NULL,
  status text NOT NULL,
  score double precision NOT NULL,
  confidence double precision,
  methodology_version text NOT NULL,
  evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  score_components_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT infrastructure_assessment_score_range CHECK (score >= 0 AND score <= 100),
  CONSTRAINT infrastructure_assessment_confidence_range
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  CONSTRAINT infrastructure_assessment_target_present
    CHECK (affected_asset_id IS NOT NULL OR affected_region IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_assessment_event_type
  ON infrastructure_assessments (event_id, assessment_type);
CREATE INDEX IF NOT EXISTS ix_assessment_asset
  ON infrastructure_assessments (affected_asset_id);
CREATE INDEX IF NOT EXISTS ix_assessment_status_score
  ON infrastructure_assessments (status, score);
CREATE INDEX IF NOT EXISTS ix_assessment_methodology
  ON infrastructure_assessments (event_id, methodology_version);
