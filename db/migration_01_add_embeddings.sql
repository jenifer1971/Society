-- Migration 01: add vector embedding columns to graph_nodes and graph_edges
-- Run this if you already have an existing society database and need to add
-- semantic search support.
--
-- Usage (from the project root):
--   docker exec -i society-db psql -U society society < db/migration_01_add_embeddings.sql

CREATE EXTENSION IF NOT EXISTS "vector";

ALTER TABLE graph_nodes
    ADD COLUMN IF NOT EXISTS embedding vector(768);

ALTER TABLE graph_edges
    ADD COLUMN IF NOT EXISTS embedding vector(768);

-- IVFFlat indexes — created AFTER populating embeddings is more efficient,
-- but safe to create now (they will be empty and auto-populated as rows are added).
CREATE INDEX IF NOT EXISTS idx_graph_nodes_embedding
    ON graph_nodes USING ivfflat (embedding vector_cosine_ops) WITH (lists = 50);

CREATE INDEX IF NOT EXISTS idx_graph_edges_embedding
    ON graph_edges USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
