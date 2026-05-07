-- Migration 02: temporal tracking support
-- Run this against an existing database that was created before schema v2.
-- Safe to run multiple times (all operations are idempotent).

-- graph_edges: ensure valid_at defaults to creation time and temporal columns exist
ALTER TABLE graph_edges
    ALTER COLUMN valid_at SET DEFAULT NOW();

ALTER TABLE graph_edges
    ADD COLUMN IF NOT EXISTS invalid_at  TIMESTAMPTZ;

ALTER TABLE graph_edges
    ADD COLUMN IF NOT EXISTS expired_at  TIMESTAMPTZ;

-- graph_episodes: track which simulation round produced each episode
ALTER TABLE graph_episodes
    ADD COLUMN IF NOT EXISTS round_num INTEGER NOT NULL DEFAULT 0;

-- Full-text search index on facts (keyword fallback / Anthropic users)
CREATE INDEX IF NOT EXISTS idx_graph_edges_fact_fts
    ON graph_edges USING gin(to_tsvector('simple', fact));
