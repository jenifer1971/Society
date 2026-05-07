"""
Entity reader — reads nodes and edges from PostgreSQL.

The public API (ZepEntityReader, EntityNode, FilteredEntities) is unchanged
so all callers continue to work without modification.
"""

from typing import Dict, Any, List, Optional, Set, TypeVar
from dataclasses import dataclass, field

from ..db import get_conn
from ..utils.logger import get_logger

logger = get_logger('mirofish.zep_entity_reader')

T = TypeVar('T')


@dataclass
class EntityNode:
    """Entity node data structure."""
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    related_edges: List[Dict[str, Any]] = field(default_factory=list)
    related_nodes: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes,
            "related_edges": self.related_edges,
            "related_nodes": self.related_nodes,
        }

    def get_entity_type(self) -> Optional[str]:
        for label in self.labels:
            if label not in ("Entity", "Node"):
                return label
        return None

    def get_primary_label(self) -> str:
        entity_type = self.get_entity_type()
        return entity_type or "Entity"


@dataclass
class FilteredEntities:
    """Result of entity filtering."""
    defined_entities: Dict[str, List[EntityNode]] = field(default_factory=dict)
    undefined_entities: List[EntityNode] = field(default_factory=list)
    total_nodes: int = 0
    defined_count: int = 0
    undefined_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "defined_entities": {
                k: [e.to_dict() for e in v]
                for k, v in self.defined_entities.items()
            },
            "undefined_entities": [e.to_dict() for e in self.undefined_entities],
            "total_nodes": self.total_nodes,
            "defined_count": self.defined_count,
            "undefined_count": self.undefined_count,
        }

    def get_all_defined(self) -> List[EntityNode]:
        result: List[EntityNode] = []
        for entities in self.defined_entities.values():
            result.extend(entities)
        return result

    def get_by_type(self, entity_type: str) -> List[EntityNode]:
        return self.defined_entities.get(entity_type, [])


class ZepEntityReader:
    """Reads entities and edges from PostgreSQL."""

    def __init__(self, base_url: Optional[str] = None):
        # base_url kept for signature compatibility — not used
        pass

    # ── Nodes ──────────────────────────────────────────────────────────────────

    def get_all_nodes(self, graph_id: str) -> List[EntityNode]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, name, labels, summary, attributes
                       FROM graph_nodes WHERE graph_id = %s
                       ORDER BY created_at""",
                    (graph_id,),
                )
                rows = cur.fetchall()

        return [
            EntityNode(
                uuid=str(r[0]),
                name=r[1] or "",
                labels=r[2] or ["Entity"],
                summary=r[3] or "",
                attributes=r[4] or {},
            )
            for r in rows
        ]

    # ── Edges ──────────────────────────────────────────────────────────────────

    def get_all_edges(self, graph_id: str) -> List[Dict[str, Any]]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, name, fact, source_node_id, target_node_id,
                              source_node_name, target_node_name,
                              valid_at, invalid_at, expired_at, created_at
                       FROM graph_edges WHERE graph_id = %s
                       ORDER BY created_at""",
                    (graph_id,),
                )
                rows = cur.fetchall()

        return [
            {
                "uuid": str(r[0]),
                "name": r[1] or "",
                "fact": r[2] or "",
                "source_node_uuid": str(r[3]) if r[3] else "",
                "target_node_uuid": str(r[4]) if r[4] else "",
                "source_node_name": r[5] or "",
                "target_node_name": r[6] or "",
                "valid_at": str(r[7]) if r[7] else None,
                "invalid_at": str(r[8]) if r[8] else None,
                "expired_at": str(r[9]) if r[9] else None,
                "created_at": str(r[10]) if r[10] else None,
            }
            for r in rows
        ]

    # ── Filtering ──────────────────────────────────────────────────────────────

    def filter_defined_entities(
        self,
        graph_id: str,
        defined_types: Optional[Set[str]] = None,
        max_per_type: Optional[int] = None,
    ) -> FilteredEntities:
        nodes = self.get_all_nodes(graph_id)
        result = FilteredEntities(total_nodes=len(nodes))

        for node in nodes:
            entity_type = node.get_entity_type()
            if defined_types is None or (entity_type and entity_type in defined_types):
                key = entity_type or "Entity"
                bucket = result.defined_entities.setdefault(key, [])
                if max_per_type is None or len(bucket) < max_per_type:
                    bucket.append(node)
                    result.defined_count += 1
            else:
                result.undefined_entities.append(node)
                result.undefined_count += 1

        return result

    def get_entity_with_context(self, graph_id: str, node_uuid: str) -> Optional[EntityNode]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, labels, summary, attributes FROM graph_nodes WHERE id = %s",
                    (node_uuid,),
                )
                row = cur.fetchone()
                if not row:
                    return None

                node = EntityNode(
                    uuid=str(row[0]),
                    name=row[1] or "",
                    labels=row[2] or ["Entity"],
                    summary=row[3] or "",
                    attributes=row[4] or {},
                )

                # Attach related edges
                cur.execute(
                    """SELECT id, name, fact, source_node_id, target_node_id,
                              source_node_name, target_node_name
                       FROM graph_edges
                       WHERE source_node_id = %s OR target_node_id = %s""",
                    (node_uuid, node_uuid),
                )
                edge_rows = cur.fetchall()

        node.related_edges = [
            {
                "uuid": str(e[0]),
                "name": e[1] or "",
                "fact": e[2] or "",
                "source_node_uuid": str(e[3]) if e[3] else "",
                "target_node_uuid": str(e[4]) if e[4] else "",
                "source_node_name": e[5] or "",
                "target_node_name": e[6] or "",
            }
            for e in edge_rows
        ]
        return node

    def get_entities_by_type(self, graph_id: str, entity_type: str) -> List[EntityNode]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, name, labels, summary, attributes
                       FROM graph_nodes
                       WHERE graph_id = %s AND labels @> %s::jsonb""",
                    (graph_id, f'["{entity_type}"]'),
                )
                rows = cur.fetchall()

        return [
            EntityNode(
                uuid=str(r[0]),
                name=r[1] or "",
                labels=r[2] or ["Entity"],
                summary=r[3] or "",
                attributes=r[4] or {},
            )
            for r in rows
        ]
