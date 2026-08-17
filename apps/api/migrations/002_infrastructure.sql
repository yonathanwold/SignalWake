-- Phase 2 infrastructure reference data. 001_initial.sql remains the event schema.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS infrastructure_sources (
  id uuid PRIMARY KEY,
  key text NOT NULL UNIQUE,
  name text NOT NULL,
  endpoint text NOT NULL,
  attribution text NOT NULL,
  license text NOT NULL,
  adapter_version text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  last_import_at timestamptz,
  last_import_count integer,
  last_import_error text
);

CREATE TABLE IF NOT EXISTS raw_infrastructure_records (
  id uuid PRIMARY KEY,
  source_id uuid NOT NULL REFERENCES infrastructure_sources(id),
  source_record_id text NOT NULL,
  source_updated_at timestamptz,
  fetched_at timestamptz NOT NULL,
  payload jsonb NOT NULL,
  payload_hash text NOT NULL,
  processing_state text NOT NULL,
  adapter_version text NOT NULL,
  UNIQUE (source_id, payload_hash)
);

CREATE TABLE IF NOT EXISTS infrastructure_assets (
  id uuid PRIMARY KEY,
  source_id uuid NOT NULL REFERENCES infrastructure_sources(id),
  raw_infrastructure_record_id uuid REFERENCES raw_infrastructure_records(id),
  source_asset_id text NOT NULL,
  name text NOT NULL,
  asset_type text NOT NULL,
  asset_subtype text,
  operator text,
  owner text,
  status text,
  region text,
  latitude double precision,
  longitude double precision,
  geometry_type text NOT NULL,
  geometry_geojson jsonb NOT NULL,
  geometry geometry(Geometry, 4326) NOT NULL,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  provenance_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  payload_hash text NOT NULL,
  classification text NOT NULL DEFAULT 'REFERENCE',
  source_updated_at timestamptz,
  imported_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  normalized_version text NOT NULL,
  UNIQUE (source_id, source_asset_id)
);

CREATE INDEX IF NOT EXISTS ix_infrastructure_assets_geometry_gist
  ON infrastructure_assets USING gist (geometry);
CREATE INDEX IF NOT EXISTS ix_infrastructure_assets_source_type
  ON infrastructure_assets (source_id, asset_type);
CREATE INDEX IF NOT EXISTS ix_infrastructure_assets_type_region
  ON infrastructure_assets (asset_type, region);
CREATE INDEX IF NOT EXISTS ix_infrastructure_assets_source_record
  ON raw_infrastructure_records (source_id, source_record_id);

-- Production viewport predicate. The API uses this shape on PostgreSQL/PostGIS:
-- ST_Intersects(geometry, ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326))
-- Distances use geography semantics to return metres:
-- ST_DWithin(geometry::geography, ST_SetSRID(ST_Point(:lon, :lat), 4326)::geography, :metres)
