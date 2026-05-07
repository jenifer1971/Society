"""
Temporal fact tracker — detects when simulation agent activities contradict
existing knowledge-graph facts and marks the old facts as invalid.

How it works (one LLM call per activity batch):
  1. Retrieve existing edges for the entities seen in this activity batch
     using the hybrid vector + keyword search already in ZepToolsService.
  2. Send one prompt to the LLM:
       "Here are existing facts.  Here are new activities.
        Which existing facts are now contradicted?
        What new facts should be added?"
  3. Mark contradicted edges with invalid_at = NOW().
  4. Insert new fact-edges with valid_at = NOW().

Configuration:
  ENABLE_TEMPORAL_TRACKING=true   in .env activates this (default: false).
  The tracker runs in the same background thread as the memory updater so it
  never blocks the simulation loop.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..db import get_conn
from ..embedding import EmbeddingClient, _vec_str
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger

logger = get_logger('mirofish.temporal_tracker')

_SYSTEM_PROMPT = """\
You analyse social-media simulation activities and update a knowledge graph.

You will receive:
  A) EXISTING FACTS — edges already in the graph, each with an ID.
  B) NEW ACTIVITIES — what agents just did in the simulation.

Your tasks:
  1. Identify existing facts that are now CONTRADICTED or SUPERSEDED by the
     new activities (e.g. an agent that "supported policy X" just posted
     against it — the support edge is now invalid).
  2. Extract NEW facts from the activities worth adding to the graph.

Return ONLY valid JSON — no prose, no markdown fences:
{
  "invalidate": ["<edge_id>", ...],
  "new_facts": [
    {
      "source": "<entity name>",
      "relation": "<RELATION_TYPE>",
      "target": "<entity name>",
      "fact": "<one sentence stating the fact>"
    }
  ]
}

Rules:
- Only invalidate when there is a clear contradiction, not just new information.
- Keep new_facts short (≤ 5) and only include facts with lasting significance.
- If nothing is contradicted and no significant new facts arise, return
  {"invalidate": [], "new_facts": []}.
"""


class TemporalTracker:
    """
    Called by ZepGraphMemoryUpdater after every activity batch is stored.
    Detects contradictions and keeps the graph temporally consistent.
    """

    # Cosine distance threshold for "same topic" candidate edges.
    # Lower = only very similar; 0 is identical, 2 is maximally different.
    _SIMILARITY_THRESHOLD = 0.35

    # Maximum number of existing edges to include in the LLM prompt.
    _MAX_CANDIDATE_EDGES = 20

    def __init__(self):
        self._llm: Optional[LLMClient] = None
        self._embedder: Optional[EmbeddingClient] = None

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = LLMClient()
        return self._llm

    @property
    def embedder(self) -> EmbeddingClient:
        if self._embedder is None:
            self._embedder = EmbeddingClient()
        return self._embedder

    # ── Public entry point ─────────────────────────────────────────────────────

    def process_activity_batch(
        self,
        graph_id: str,
        activity_text: str,
        round_num: int = 0,
    ) -> None:
        """
        Analyse a batch of agent activities and update edge temporal metadata.
        Safe to call from a background thread — all DB operations are atomic.
        """
        try:
            candidate_edges = self._find_candidate_edges(graph_id, activity_text)
            if not candidate_edges:
                return

            result = self._analyse_with_llm(activity_text, candidate_edges)
            if not result:
                return

            self._apply_changes(graph_id, result, round_num)

        except Exception as e:
            logger.warning(f"Temporal tracking failed for graph {graph_id}: {e}")

    # ── Step 1: find candidate edges ───────────────────────────────────────────

    def _find_candidate_edges(
        self, graph_id: str, activity_text: str
    ) -> List[Dict[str, Any]]:
        """
        Return existing edges that are topically related to the activity text.
        Uses vector search when embeddings are available, falls back to keyword.
        """
        query_vec = self.embedder.embed(activity_text) if self.embedder.supported() else None
        candidates: List[Dict[str, Any]] = []

        if query_vec:
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """SELECT id, name, fact, source_node_name, target_node_name,
                                      (embedding <=> %s::vector) AS distance
                               FROM graph_edges
                               WHERE graph_id = %s
                                 AND invalid_at IS NULL
                                 AND expired_at IS NULL
                                 AND embedding IS NOT NULL
                               ORDER BY embedding <=> %s::vector
                               LIMIT %s""",
                            (
                                _vec_str(query_vec), graph_id,
                                _vec_str(query_vec), self._MAX_CANDIDATE_EDGES,
                            ),
                        )
                        for row in cur.fetchall():
                            dist = float(row[5])
                            if dist <= self._SIMILARITY_THRESHOLD:
                                candidates.append({
                                    "id": str(row[0]),
                                    "relation": row[1] or "",
                                    "fact": row[2] or "",
                                    "source": row[3] or "",
                                    "target": row[4] or "",
                                })
            except Exception as e:
                logger.debug(f"Vector candidate search failed: {e}")

        # Keyword fallback (also supplements vector results for exact names)
        if not candidates:
            keywords = [
                w.strip() for w in activity_text.lower().split()
                if len(w.strip()) > 2
            ]
            if not keywords:
                return []
            like_clauses = " OR ".join(
                "LOWER(fact) LIKE %s" for _ in keywords[:10]
            )
            params = [f"%{kw}%" for kw in keywords[:10]] + [graph_id]
            try:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"""SELECT id, name, fact, source_node_name, target_node_name
                                FROM graph_edges
                                WHERE ({like_clauses})
                                  AND graph_id = %s
                                  AND invalid_at IS NULL
                                  AND expired_at IS NULL
                                LIMIT {self._MAX_CANDIDATE_EDGES}""",
                            params,
                        )
                        for row in cur.fetchall():
                            candidates.append({
                                "id": str(row[0]),
                                "relation": row[1] or "",
                                "fact": row[2] or "",
                                "source": row[3] or "",
                                "target": row[4] or "",
                            })
            except Exception as e:
                logger.debug(f"Keyword candidate search failed: {e}")

        return candidates

    # ── Step 2: LLM analysis ───────────────────────────────────────────────────

    def _analyse_with_llm(
        self,
        activity_text: str,
        candidate_edges: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Ask the LLM which edges to invalidate and what new facts to add."""
        existing_block = "\n".join(
            f'  [{e["id"]}] {e["source"]} --[{e["relation"]}]--> {e["target"]}: "{e["fact"]}"'
            for e in candidate_edges
        )
        user_prompt = (
            f"A) EXISTING FACTS:\n{existing_block}\n\n"
            f"B) NEW ACTIVITIES:\n{activity_text}"
        )

        try:
            return self.llm.chat_json(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.1,
            )
        except Exception as e:
            logger.warning(f"LLM temporal analysis failed: {e}")
            return None

    # ── Step 3: apply changes ──────────────────────────────────────────────────

    def _apply_changes(
        self,
        graph_id: str,
        result: Dict[str, Any],
        round_num: int,
    ) -> None:
        """Invalidate old edges and insert new fact-edges."""
        to_invalidate: List[str] = result.get("invalidate", [])
        new_facts: List[Dict] = result.get("new_facts", [])

        now = datetime.now(timezone.utc)

        with get_conn() as conn:
            with conn.cursor() as cur:
                # Mark old edges as invalid
                for edge_id in to_invalidate:
                    cur.execute(
                        "UPDATE graph_edges SET invalid_at = %s WHERE id = %s AND graph_id = %s",
                        (now, edge_id, graph_id),
                    )
                    if cur.rowcount:
                        logger.info(
                            f"Marked edge {edge_id[:8]} as invalid (round {round_num})"
                        )

                # Insert new fact-edges
                for nf in new_facts[:5]:  # cap at 5 per batch
                    source = (nf.get("source") or "").strip()
                    target = (nf.get("target") or "").strip()
                    relation = (nf.get("relation") or "RELATED_TO").strip()
                    fact = (nf.get("fact") or "").strip()
                    if not source or not target or not fact:
                        continue

                    src_id = self._find_or_create_node(cur, graph_id, source)
                    tgt_id = self._find_or_create_node(cur, graph_id, target)

                    edge_id = str(uuid.uuid4())
                    cur.execute(
                        """INSERT INTO graph_edges
                               (id, graph_id, name, fact,
                                source_node_id, target_node_id,
                                source_node_name, target_node_name,
                                valid_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (edge_id, graph_id, relation, fact,
                         src_id, tgt_id, source, target, now),
                    )
                    logger.info(
                        f"Added new temporal edge: {source} --[{relation}]--> {target}"
                    )

                    # Generate embedding for the new edge (outside lock to avoid blocking)
                    self._embed_edge_async(edge_id, fact)

        if to_invalidate or new_facts:
            logger.info(
                f"Temporal update (round {round_num}): "
                f"{len(to_invalidate)} invalidated, {len(new_facts)} added"
            )

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
            "INSERT INTO graph_nodes (id, graph_id, name, labels, summary) VALUES (%s,%s,%s,%s,%s)",
            (node_id, graph_id, name, json.dumps(["Entity"]), ""),
        )
        return node_id

    def _embed_edge_async(self, edge_id: str, fact: str) -> None:
        """Generate and store embedding for a new edge in the background."""
        import threading

        def _do():
            try:
                vec = self.embedder.embed(fact)
                if vec:
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "UPDATE graph_edges SET embedding = %s::vector WHERE id = %s",
                                (_vec_str(vec), edge_id),
                            )
            except Exception as e:
                logger.debug(f"Async embed failed for edge {edge_id[:8]}: {e}")

        threading.Thread(target=_do, daemon=True).start()
