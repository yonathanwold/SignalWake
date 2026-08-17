CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS sources (
  id uuid PRIMARY KEY,
  key text NOT NULL UNIQUE,
  name text NOT NULL,
  kind text NOT NULL,
  endpoint text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  adapter_version text NOT NULL,
  last_success_at timestamptz,
  last_attempt_at timestamptz,
  last_error text,
  last_http_status integer,
  freshness_seconds integer
);

CREATE TABLE IF NOT EXISTS raw_observations (
  id uuid PRIMARY KEY,
  source_id uuid NOT NULL REFERENCES sources(id),
  source_record_id text NOT NULL,
  observed_at timestamptz NOT NULL,
  fetched_at timestamptz NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  processing_state text NOT NULL,
  adapter_version text NOT NULL,
  UNIQUE (source_id, payload_hash)
);

CREATE TABLE IF NOT EXISTS events (
  id uuid PRIMARY KEY,
  source_id uuid NOT NULL REFERENCES sources(id),
  raw_observation_id uuid REFERENCES raw_observations(id),
  source_event_id text NOT NULL,
  event_type text NOT NULL,
  title text NOT NULL,
  summary text,
  severity text NOT NULL,
  status text NOT NULL,
  observed_at timestamptz NOT NULL,
  effective_at timestamptz,
  expires_at timestamptz,
  received_at timestamptz NOT NULL,
  latitude double precision,
  longitude double precision,
  geometry geometry(Geometry, 4326),
  provenance jsonb NOT NULL DEFAULT '[]'::jsonb,
  payload_hash text NOT NULL,
  normalized_version text NOT NULL,
  classification text NOT NULL DEFAULT 'LIVE',
  UNIQUE (source_id, source_event_id)
);

CREATE INDEX IF NOT EXISTS ix_events_geometry_gist ON events USING gist (geometry);
CREATE INDEX IF NOT EXISTS ix_events_observed_at ON events (observed_at DESC);
CREATE INDEX IF NOT EXISTS ix_events_source_type_severity ON events (source_id, event_type, severity);

-- Production bbox semantics. ST_Intersects includes polygons and points.
-- WHERE ST_Intersects(geometry, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))

