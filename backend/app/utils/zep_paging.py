"""
Graph pagination helpers — replaced Zep SDK paging with direct SQL.

The old callers imported fetch_all_nodes / fetch_all_edges; those names are
preserved here so no import sites need to change.  The first argument (client)
is accepted but ignored for backward compatibility.
"""

from __future__ import annotations
from typing import Any, List
from ..db import get_conn


class _FakeNode:
    """Thin wrapper around a postgres row so old attribute-access code still works."""
    def __init__(self, row):
        self.uuid_ = str(row[0])
        self.uuid = str(row[0])
        self.name = row[1] or ""
        self.labels = row[2] or ["Entity"]
        self.summary = row[3] or ""
        self.attributes = row[4] or {}
        self.created_at = row[5]


class _FakeEdge:
    """Thin wrapper around a postgres edge row."""
    def __init__(self, row):
        self.uuid_ = str(row[0])
        self.uuid = str(row[0])
        self.name = row[1] or ""
        self.fact = row[2] or ""
        self.source_node_uuid = str(row[3]) if row[3] else ""
        self.target_node_uuid = str(row[4]) if row[4] else ""
        self.source_node_name = row[5] or ""
        self.target_node_name = row[6] or ""
        self.valid_at = row[7]
        self.invalid_at = row[8]
        self.expired_at = row[9]
        self.created_at = row[10]
        self.attributes = {}


def fetch_all_nodes(client: Any, graph_id: str, **kwargs) -> List[_FakeNode]:
    """Return all nodes for a graph as _FakeNode objects."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, labels, summary, attributes, created_at
                   FROM graph_nodes WHERE graph_id = %s ORDER BY created_at""",
                (graph_id,),
            )
            rows = cur.fetchall()
    return [_FakeNode(r) for r in rows]


def fetch_all_edges(client: Any, graph_id: str, **kwargs) -> List[_FakeEdge]:
    """Return all edges for a graph as _FakeEdge objects."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, name, fact, source_node_id, target_node_id,
                          source_node_name, target_node_name,
                          valid_at, invalid_at, expired_at, created_at
                   FROM graph_edges WHERE graph_id = %s ORDER BY created_at""",
                (graph_id,),
            )
            rows = cur.fetchall()
    return [_FakeEdge(r) for r in rows]
