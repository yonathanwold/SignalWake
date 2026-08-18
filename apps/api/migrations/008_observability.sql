-- Phase 8 bounded operational telemetry.  These fields describe the latest
-- source attempt/failure; request metrics remain process-local in memory.
ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_failure_at timestamptz;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS last_error_category text;
ALTER TABLE infrastructure_sources ADD COLUMN IF NOT EXISTS last_success_at timestamptz;
ALTER TABLE infrastructure_sources ADD COLUMN IF NOT EXISTS last_attempt_at timestamptz;
ALTER TABLE infrastructure_sources ADD COLUMN IF NOT EXISTS last_failure_at timestamptz;
ALTER TABLE infrastructure_sources ADD COLUMN IF NOT EXISTS last_error_category text;
ALTER TABLE transformation_runs ADD COLUMN IF NOT EXISTS error_category text;

CREATE INDEX IF NOT EXISTS ix_transformation_run_status_completed
  ON transformation_runs (status, completed_at);
