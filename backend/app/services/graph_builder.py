"""
Graph building service — extracts entities and relationships from documents
using the LLM, then stores them in PostgreSQL (pgvector-enabled).

Public API is identical to the old Zep-based implementation so all callers
are unaffected.
"""

import uuid
import json
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

from ..config import Config
from ..db import get_conn
from ..models.task import TaskManager, TaskStatus
from ..utils.llm_client import LLMClient
from .text_processor import TextProcessor
from ..utils.locale import t, get_locale, set_locale
from ..utils.logger import get_logger

logger = get_logger('mirofish.graph_builder')


@dataclass
class GraphInfo:
    """Graph summary returned after a build."""
    graph_id: str
    node_count: int
    edge_count: int
    entity_types: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "entity_types": self.entity_types,
        }


class GraphBuilderService:
    """
    Builds a knowledge graph from raw text using the configured LLM.

    For each text chunk the LLM is prompted to extract:
      • entity nodes  — name, type (from ontology), one-sentence summary
      • edge triples  — (source_entity, relation_type, target_entity, fact sentence)

    Everything is stored in PostgreSQL; no external NLP service is required.
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        # base_url / api_key kept for signature compatibility — not used
        self.task_manager = TaskManager()
        self._llm: Optional[LLMClient] = None

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    # ── Public async entry point ───────────────────────────────────────────────

    def build_graph_async(
        self,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str = "Society Graph",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        batch_size: int = 3,
    ) -> str:
        task_id = self.task_manager.create_task(
            task_type="graph_build",
            metadata={
                "graph_name": graph_name,
                "chunk_size": chunk_size,
                "text_length": len(text),
            },
        )

        current_locale = get_locale()
        thread = threading.Thread(
            target=self._build_graph_worker,
            args=(task_id, text, ontology, graph_name, chunk_size, chunk_overlap, batch_size, current_locale),
            daemon=True,
        )
        thread.start()
        return task_id

    # ── Worker ─────────────────────────────────────────────────────────────────

    def _build_graph_worker(
        self,
        task_id: str,
        text: str,
        ontology: Dict[str, Any],
        graph_name: str,
        chunk_size: int,
        chunk_overlap: int,
        batch_size: int,
        locale: str = 'zh',
    ):
        set_locale(locale)
        try:
            self.task_manager.update_task(task_id, status=TaskStatus.PROCESSING, progress=5,
                                          message=t('progress.startBuildingGraph'))

            graph_id = self.create_graph(graph_name)
            self.task_manager.update_task(task_id, progress=10,
                                          message=t('progress.graphCreated', graphId=graph_id))

            self.set_ontology(graph_id, ontology)
            self.task_manager.update_task(task_id, progress=15,
                                          message=t('progress.ontologySet'))

            chunks = TextProcessor.split_text(text, chunk_size, chunk_overlap)
            total_chunks = len(chunks)
            self.task_manager.update_task(task_id, progress=20,
                                          message=t('progress.textSplit', count=total_chunks))

            self.add_text_batches(
                graph_id, chunks, batch_size, ontology,
                lambda msg, prog: self.task_manager.update_task(
                    task_id,
                    progress=20 + int(prog * 0.70),  # 20–90 %
                    message=msg,
                ),
            )

            graph_info = self._get_graph_info(graph_id)
            self.task_manager.complete_task(task_id, {
                "graph_id": graph_id,
                "graph_info": graph_info.to_dict(),
                "chunks_processed": total_chunks,
            })

        except Exception as e:
            import traceback
            self.task_manager.fail_task(task_id, f"{e}\n{traceback.format_exc()}")

    # ── Graph lifecycle ────────────────────────────────────────────────────────

    def create_graph(self, name: str) -> str:
        graph_id = f"mirofish_{uuid.uuid4().hex[:16]}"
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO graphs (id, name) VALUES (%s, %s)",
                    (graph_id, name),
                )
        logger.info(f"Created graph: {graph_id}")
        return graph_id

    def set_ontology(self, graph_id: str, ontology: Dict[str, Any]):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE graphs SET ontology = %s WHERE id = %s",
                    (json.dumps(ontology), graph_id),
                )

    def delete_graph(self, graph_id: str):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM graphs WHERE id = %s", (graph_id,))
        logger.info(f"Deleted graph: {graph_id}")

    # ── Text ingestion ─────────────────────────────────────────────────────────

    def add_text_batches(
        self,
        graph_id: str,
        chunks: List[str],
        batch_size: int = 3,
        ontology: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable] = None,
    ) -> List[str]:
        """
        Process text chunks, extract entities/relations with the LLM, persist to postgres.
        Returns list of placeholder episode IDs (one per chunk) for API compatibility.
        """
        if ontology is None:
            ontology = self._load_ontology(graph_id)

        episode_ids: List[str] = []
        total = len(chunks)

        for i, chunk in enumerate(chunks):
            batch_num = i + 1
            if progress_callback:
                progress_callback(
                    t('progress.sendingBatch', current=batch_num, total=total, chunks=1),
                    (i + 1) / total,
                )

            try:
                extraction = self._extract_from_chunk(chunk, ontology)
                ep_id = self._persist_extraction(graph_id, chunk, extraction)
                episode_ids.append(ep_id)
            except Exception as e:
                logger.warning(f"Extraction failed for chunk {batch_num}: {e}")

        return episode_ids

    def _load_ontology(self, graph_id: str) -> Dict[str, Any]:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT ontology FROM graphs WHERE id = %s", (graph_id,))
                row = cur.fetchone()
                return row[0] if row and row[0] else {}

    # ── LLM extraction ─────────────────────────────────────────────────────────

    def _extract_from_chunk(self, chunk: str, ontology: Dict[str, Any]) -> Dict[str, Any]:
        """Ask the LLM to extract entities and relationships from a text chunk."""
        entity_types = [e.get("name", "") for e in ontology.get("entity_types", [])]
        edge_types = [e.get("name", "") for e in ontology.get("edge_types", [])]

        entity_type_str = ", ".join(entity_types) if entity_types else "Person, Organization, Location, Event, Concept"
        edge_type_str = ", ".join(edge_types) if edge_types else "RELATED_TO, BELONGS_TO, INTERACTS_WITH"

        prompt = f"""Extract entities and relationships from the following text.

Entity types to use: {entity_type_str}
Relationship types to use: {edge_type_str}

Return ONLY valid JSON with this exact structure:
{{
  "entities": [
    {{"name": "entity name", "type": "EntityType", "summary": "one sentence description"}}
  ],
  "relationships": [
    {{"source": "source entity name", "relation": "RELATION_TYPE", "target": "target entity name", "fact": "full sentence stating the fact"}}
  ]
}}

Text to analyze:
{chunk}"""

        try:
            result = self.llm.chat_json([{"role": "user", "content": prompt}])
            if isinstance(result, dict):
                return result
        except Exception as e:
            logger.warning(f"LLM extraction error: {e}")

        return {"entities": [], "relationships": []}

    # ── Persistence ────────────────────────────────────────────────────────────

    def _persist_extraction(
        self, graph_id: str, chunk: str, extraction: Dict[str, Any]
    ) -> str:
        """Store extracted entities and relationships in postgres. Returns episode id."""
        episode_id = str(uuid.uuid4())

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Store the raw text as an episode
                cur.execute(
                    "INSERT INTO graph_episodes (id, graph_id, content) VALUES (%s, %s, %s)",
                    (episode_id, graph_id, chunk),
                )

                # Upsert entities → collect name→uuid mapping
                node_map: Dict[str, str] = {}
                for ent in extraction.get("entities", []):
                    name = (ent.get("name") or "").strip()
                    etype = (ent.get("type") or "Entity").strip()
                    summary = (ent.get("summary") or "").strip()
                    if not name:
                        continue

                    labels = json.dumps(["Entity", etype] if etype != "Entity" else ["Entity"])

                    # Check if node already exists for this graph
                    cur.execute(
                        "SELECT id FROM graph_nodes WHERE graph_id = %s AND name = %s",
                        (graph_id, name),
                    )
                    existing = cur.fetchone()
                    if existing:
                        node_id = str(existing[0])
                        if summary:
                            cur.execute(
                                "UPDATE graph_nodes SET summary = %s WHERE id = %s",
                                (summary, node_id),
                            )
                    else:
                        node_id = str(uuid.uuid4())
                        cur.execute(
                            """INSERT INTO graph_nodes (id, graph_id, name, labels, summary)
                               VALUES (%s, %s, %s, %s, %s)""",
                            (node_id, graph_id, name, labels, summary),
                        )
                    node_map[name.lower()] = node_id

                # Insert relationships
                for rel in extraction.get("relationships", []):
                    src_name = (rel.get("source") or "").strip()
                    tgt_name = (rel.get("target") or "").strip()
                    rel_type = (rel.get("relation") or "RELATED_TO").strip()
                    fact = (rel.get("fact") or "").strip()
                    if not src_name or not tgt_name:
                        continue

                    src_id = node_map.get(src_name.lower())
                    tgt_id = node_map.get(tgt_name.lower())

                    # Resolve nodes that weren't in this chunk's entity list
                    if not src_id:
                        src_id = self._find_or_create_node(cur, graph_id, src_name)
                        node_map[src_name.lower()] = src_id
                    if not tgt_id:
                        tgt_id = self._find_or_create_node(cur, graph_id, tgt_name)
                        node_map[tgt_name.lower()] = tgt_id

                    cur.execute(
                        """INSERT INTO graph_edges
                               (id, graph_id, name, fact, source_node_id, target_node_id,
                                source_node_name, target_node_name)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                        (str(uuid.uuid4()), graph_id, rel_type, fact,
                         src_id, tgt_id, src_name, tgt_name),
                    )

        return episode_id

    def _find_or_create_node(self, cur, graph_id: str, name: str) -> str:
        cur.execute(
            "SELECT id FROM graph_nodes WHERE graph_id = %s AND name = %s",
            (graph_id, name),
        )
        row = cur.fetchone()
        if row:
            return str(row[0])
        node_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO graph_nodes (id, graph_id, name, labels, summary) VALUES (%s, %s, %s, %s, %s)",
            (node_id, graph_id, name, json.dumps(["Entity"]), ""),
        )
        return node_id

    # ── Graph info / export ────────────────────────────────────────────────────

    def _get_graph_info(self, graph_id: str) -> GraphInfo:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM graph_nodes WHERE graph_id = %s", (graph_id,))
                node_count = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM graph_edges WHERE graph_id = %s", (graph_id,))
                edge_count = cur.fetchone()[0]

                cur.execute("SELECT labels FROM graph_nodes WHERE graph_id = %s", (graph_id,))
                rows = cur.fetchall()

        entity_types: set = set()
        for (labels,) in rows:
            for label in (labels or []):
                if label not in ("Entity", "Node"):
                    entity_types.add(label)

        return GraphInfo(
            graph_id=graph_id,
            node_count=node_count,
            edge_count=edge_count,
            entity_types=sorted(entity_types),
        )

    def get_graph_data(self, graph_id: str) -> Dict[str, Any]:
        """Return full graph data (nodes + edges) for the frontend."""
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, name, labels, summary, attributes, created_at
                       FROM graph_nodes WHERE graph_id = %s""",
                    (graph_id,),
                )
                node_rows = cur.fetchall()

                cur.execute(
                    """SELECT id, name, fact, source_node_id, target_node_id,
                              source_node_name, target_node_name,
                              valid_at, invalid_at, expired_at, created_at
                       FROM graph_edges WHERE graph_id = %s""",
                    (graph_id,),
                )
                edge_rows = cur.fetchall()

        nodes_data = [
            {
                "uuid": str(r[0]),
                "name": r[1],
                "labels": r[2] or [],
                "summary": r[3] or "",
                "attributes": r[4] or {},
                "created_at": str(r[5]) if r[5] else None,
            }
            for r in node_rows
        ]

        edges_data = [
            {
                "uuid": str(r[0]),
                "name": r[1],
                "fact": r[2] or "",
                "fact_type": r[1],
                "source_node_uuid": str(r[3]) if r[3] else "",
                "target_node_uuid": str(r[4]) if r[4] else "",
                "source_node_name": r[5] or "",
                "target_node_name": r[6] or "",
                "attributes": {},
                "valid_at": str(r[7]) if r[7] else None,
                "invalid_at": str(r[8]) if r[8] else None,
                "expired_at": str(r[9]) if r[9] else None,
                "created_at": str(r[10]) if r[10] else None,
                "episodes": [],
            }
            for r in edge_rows
        ]

        return {
            "graph_id": graph_id,
            "nodes": nodes_data,
            "edges": edges_data,
            "node_count": len(nodes_data),
            "edge_count": len(edges_data),
        }
