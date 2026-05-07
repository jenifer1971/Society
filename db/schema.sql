-- Society knowledge graph schema
-- Run automatically by the pgvector/pgvector container on first start.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ── Graphs ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS graphs (
    id          TEXT        PRIMARY KEY,
    name        TEXT        NOT NULL,
    ontology    JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Nodes (entities extracted from documents) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS graph_nodes (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    graph_id    TEXT        NOT NULL REFERENCES graphs(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    labels      JSONB       NOT NULL DEFAULT '["Entity"]',
    summary     TEXT        NOT NULL DEFAULT '',
    attributes  JSONB       NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_graph_nodes_graph_id  ON graph_nodes(graph_id);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_name       ON graph_nodes(graph_id, name);

-- ── Edges (relationships between entities) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS graph_edges (
    id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    graph_id         TEXT        NOT NULL REFERENCES graphs(id) ON DELETE CASCADE,
    name             TEXT        NOT NULL,
    fact             TEXT        NOT NULL DEFAULT '',
    source_node_id   UUID        REFERENCES graph_nodes(id) ON DELETE CASCADE,
    target_node_id   UUID        REFERENCES graph_nodes(id) ON DELETE CASCADE,
    source_node_name TEXT,
    target_node_name TEXT,
    valid_at         TIMESTAMPTZ,
    invalid_at       TIMESTAMPTZ,
    expired_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_graph_edges_graph_id  ON graph_edges(graph_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source    ON graph_edges(source_node_id);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target    ON graph_edges(target_node_id);

-- Full-text search index on facts
CREATE INDEX IF NOT EXISTS idx_graph_edges_fact_fts
    ON graph_edges USING gin(to_tsvector('simple', fact));

-- ── Episodes (agent activity logs written during simulation) ──────────────────
CREATE TABLE IF NOT EXISTS graph_episodes (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    graph_id    TEXT        NOT NULL REFERENCES graphs(id) ON DELETE CASCADE,
    content     TEXT        NOT NULL,
    platform    TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_graph_episodes_graph_id ON graph_episodes(graph_id);
