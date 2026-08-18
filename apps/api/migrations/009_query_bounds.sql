-- Phase 9 query-shape indexes.  These support bounded relationship lookups
-- and the existing deterministic list ordering without changing contracts.
CREATE INDEX IF NOT EXISTS ix_infrastructure_relationship_from_type
  ON infrastructure_relationships (from_asset_id, relationship_type);
CREATE INDEX IF NOT EXISTS ix_infrastructure_relationship_to_type
  ON infrastructure_relationships (to_asset_id, relationship_type);

CREATE INDEX IF NOT EXISTS ix_event_observed_id
  ON events (observed_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS ix_assessment_event_score
  ON infrastructure_assessments (event_id, score DESC);
CREATE INDEX IF NOT EXISTS ix_assessment_asset_score
  ON infrastructure_assessments (affected_asset_id, score DESC);
