-- Phase 3 infrastructure graph relationships.
-- Edges are source/provenance aware; the initial graph builder writes only
-- DERIVED edges and never overwrites SOURCE_OBSERVED edges.
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS infrastructure_relationships (
  id uuid PRIMARY KEY,
  from_asset_id uuid NOT NULL REFERENCES infrastructure_assets(id),
  to_asset_id uuid NOT NULL REFERENCES infrastructure_assets(id),
  relationship_key text NOT NULL UNIQUE,
  relationship_type text NOT NULL,
  directionality text NOT NULL DEFAULT 'UNDIRECTED',
  relationship_source text NOT NULL,
  source_relationship_id text,
  derivation_method text,
  derivation_version text,
  confidence double precision,
  evidence_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  distance_km double precision,
  tolerance_m double precision,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT infrastructure_relationship_confidence_range
    CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  CONSTRAINT infrastructure_relationship_endpoints_distinct
    CHECK (from_asset_id <> to_asset_id)
);

CREATE INDEX IF NOT EXISTS ix_infrastructure_relationship_from
  ON infrastructure_relationships (from_asset_id);
CREATE INDEX IF NOT EXISTS ix_infrastructure_relationship_to
  ON infrastructure_relationships (to_asset_id);
CREATE INDEX IF NOT EXISTS ix_infrastructure_relationship_type_source
  ON infrastructure_relationships (relationship_type, relationship_source);
CREATE INDEX IF NOT EXISTS ix_infrastructure_relationship_derived
  ON infrastructure_relationships (relationship_source, updated_at);

-- The graph builder uses these bounded candidate/query shapes in production:
-- ST_DWithin(a.geometry::geography, b.geometry::geography, :metres)
-- ST_Intersects(a.geometry, b.geometry)
