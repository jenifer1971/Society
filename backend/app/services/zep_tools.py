"""
Graph retrieval tools — queries PostgreSQL instead of the Zep API.

All public dataclasses and method signatures are preserved so report_agent.py
and every other caller continues to work without modification.
"""

import time
import json
import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

from ..db import get_conn
from ..config import Config
from ..utils.logger import get_logger
from ..utils.llm_client import LLMClient
from ..utils.locale import get_locale, t

logger = get_logger('mirofish.zep_tools')


# ── Dataclasses (unchanged public API) ────────────────────────────────────────

@dataclass
class SearchResult:
    facts: List[str]
    edges: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    query: str
    total_count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "facts": self.facts,
            "edges": self.edges,
            "nodes": self.nodes,
            "query": self.query,
            "total_count": self.total_count,
        }

    def to_text(self) -> str:
        text_parts = [f"搜索查询: {self.query}", f"找到 {self.total_count} 条相关信息"]
        if self.facts:
            text_parts.append("\n### 相关事实:")
            for i, fact in enumerate(self.facts, 1):
                text_parts.append(f"{i}. {fact}")
        return "\n".join(text_parts)


@dataclass
class NodeInfo:
    uuid: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "labels": self.labels,
            "summary": self.summary,
            "attributes": self.attributes,
        }

    def to_text(self) -> str:
        entity_type = next((l for l in self.labels if l not in ["Entity", "Node"]), "未知类型")
        return f"实体: {self.name} (类型: {entity_type})\n摘要: {self.summary}"


@dataclass
class EdgeInfo:
    uuid: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    source_node_name: Optional[str] = None
    target_node_name: Optional[str] = None
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "uuid": self.uuid,
            "name": self.name,
            "fact": self.fact,
            "source_node_uuid": self.source_node_uuid,
            "target_node_uuid": self.target_node_uuid,
            "source_node_name": self.source_node_name,
            "target_node_name": self.target_node_name,
            "created_at": self.created_at,
            "valid_at": self.valid_at,
            "invalid_at": self.invalid_at,
            "expired_at": self.expired_at,
        }

    def to_text(self, include_temporal: bool = False) -> str:
        source = self.source_node_name or self.source_node_uuid[:8]
        target = self.target_node_name or self.target_node_uuid[:8]
        base_text = f"关系: {source} --[{self.name}]--> {target}\n事实: {self.fact}"
        if include_temporal:
            valid_at = self.valid_at or "未知"
            invalid_at = self.invalid_at or "至今"
            base_text += f"\n时效: {valid_at} - {invalid_at}"
            if self.expired_at:
                base_text += f" (已过期: {self.expired_at})"
        return base_text

    @property
    def is_expired(self) -> bool:
        return self.expired_at is not None

    @property
    def is_invalid(self) -> bool:
        return self.invalid_at is not None


@dataclass
class InsightForgeResult:
    query: str
    simulation_requirement: str
    sub_queries: List[str]
    semantic_facts: List[str] = field(default_factory=list)
    entity_insights: List[Dict[str, Any]] = field(default_factory=list)
    relationship_chains: List[str] = field(default_factory=list)
    total_facts: int = 0
    total_entities: int = 0
    total_relationships: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "simulation_requirement": self.simulation_requirement,
            "sub_queries": self.sub_queries,
            "semantic_facts": self.semantic_facts,
            "entity_insights": self.entity_insights,
            "relationship_chains": self.relationship_chains,
            "total_facts": self.total_facts,
            "total_entities": self.total_entities,
            "total_relationships": self.total_relationships,
        }

    def to_text(self) -> str:
        text_parts = [
            "## 未来预测深度分析",
            f"分析问题: {self.query}",
            f"预测场景: {self.simulation_requirement}",
            "\n### 预测数据统计",
            f"- 相关预测事实: {self.total_facts}条",
            f"- 涉及实体: {self.total_entities}个",
            f"- 关系链: {self.total_relationships}条",
        ]
        if self.sub_queries:
            text_parts.append("\n### 分析的子问题")
            for i, sq in enumerate(self.sub_queries, 1):
                text_parts.append(f"{i}. {sq}")
        if self.semantic_facts:
            text_parts.append("\n### 【关键事实】(请在报告中引用这些原文)")
            for i, fact in enumerate(self.semantic_facts, 1):
                text_parts.append(f'{i}. "{fact}"')
        if self.entity_insights:
            text_parts.append("\n### 【核心实体】")
            for entity in self.entity_insights:
                text_parts.append(f"- **{entity.get('name', '未知')}** ({entity.get('type', '实体')})")
                if entity.get("summary"):
                    text_parts.append(f"  摘要: \"{entity.get('summary')}\"")
                if entity.get("related_facts"):
                    text_parts.append(f"  相关事实: {len(entity.get('related_facts', []))}条")
        if self.relationship_chains:
            text_parts.append("\n### 【关系链】")
            for chain in self.relationship_chains:
                text_parts.append(f"- {chain}")
        return "\n".join(text_parts)


@dataclass
class PanoramaResult:
    query: str
    all_nodes: List[NodeInfo] = field(default_factory=list)
    all_edges: List[EdgeInfo] = field(default_factory=list)
    active_facts: List[str] = field(default_factory=list)
    historical_facts: List[str] = field(default_factory=list)
    total_nodes: int = 0
    total_edges: int = 0
    active_count: int = 0
    historical_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "all_nodes": [n.to_dict() for n in self.all_nodes],
            "all_edges": [e.to_dict() for e in self.all_edges],
            "active_facts": self.active_facts,
            "historical_facts": self.historical_facts,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "active_count": self.active_count,
            "historical_count": self.historical_count,
        }

    def to_text(self) -> str:
        text_parts = [
            "## 广度搜索结果（未来全景视图）",
            f"查询: {self.query}",
            "\n### 统计信息",
            f"- 总节点数: {self.total_nodes}",
            f"- 总边数: {self.total_edges}",
            f"- 当前有效事实: {self.active_count}条",
            f"- 历史/过期事实: {self.historical_count}条",
        ]
        if self.active_facts:
            text_parts.append("\n### 【当前有效事实】(模拟结果原文)")
            for i, fact in enumerate(self.active_facts, 1):
                text_parts.append(f'{i}. "{fact}"')
        if self.historical_facts:
            text_parts.append("\n### 【历史/过期事实】(演变过程记录)")
            for i, fact in enumerate(self.historical_facts, 1):
                text_parts.append(f'{i}. "{fact}"')
        if self.all_nodes:
            text_parts.append("\n### 【涉及实体】")
            for node in self.all_nodes:
                entity_type = next((l for l in node.labels if l not in ["Entity", "Node"]), "实体")
                text_parts.append(f"- **{node.name}** ({entity_type})")
        return "\n".join(text_parts)


@dataclass
class AgentInterview:
    agent_name: str
    agent_role: str
    agent_bio: str
    question: str
    response: str
    key_quotes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "agent_bio": self.agent_bio,
            "question": self.question,
            "response": self.response,
            "key_quotes": self.key_quotes,
        }

    def to_text(self) -> str:
        text = f"**{self.agent_name}** ({self.agent_role})\n"
        text += f"_简介: {self.agent_bio}_\n\n"
        text += f"**Q:** {self.question}\n\n"
        text += f"**A:** {self.response}\n"
        if self.key_quotes:
            text += "\n**关键引言:**\n"
            for quote in self.key_quotes:
                clean_quote = quote.replace('“', '').replace('”', '').replace('"', '')
                clean_quote = clean_quote.replace('「', '').replace('」', '').strip()
                while clean_quote and clean_quote[0] in '，,；;：:、。！？\n\r\t ':
                    clean_quote = clean_quote[1:]
                skip = any(f'问题{d}' in clean_quote for d in '123456789')
                if skip:
                    continue
                if len(clean_quote) > 150:
                    dot_pos = clean_quote.find('。', 80)
                    clean_quote = clean_quote[:dot_pos + 1] if dot_pos > 0 else clean_quote[:147] + "..."
                if clean_quote and len(clean_quote) >= 10:
                    text += f'> "{clean_quote}"\n'
        return text


@dataclass
class InterviewResult:
    interview_topic: str
    interview_questions: List[str]
    selected_agents: List[Dict[str, Any]] = field(default_factory=list)
    interviews: List[AgentInterview] = field(default_factory=list)
    selection_reasoning: str = ""
    summary: str = ""
    total_agents: int = 0
    interviewed_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interview_topic": self.interview_topic,
            "interview_questions": self.interview_questions,
            "selected_agents": self.selected_agents,
            "interviews": [i.to_dict() for i in self.interviews],
            "selection_reasoning": self.selection_reasoning,
            "summary": self.summary,
            "total_agents": self.total_agents,
            "interviewed_count": self.interviewed_count,
        }

    def to_text(self) -> str:
        text_parts = [
            "## 深度采访报告",
            f"**采访主题:** {self.interview_topic}",
            f"**采访人数:** {self.interviewed_count} / {self.total_agents} 位模拟Agent",
            "\n### 采访对象选择理由",
            self.selection_reasoning or "（自动选择）",
            "\n---",
            "\n### 采访实录",
        ]
        if self.interviews:
            for i, interview in enumerate(self.interviews, 1):
                text_parts.append(f"\n#### 采访 #{i}: {interview.agent_name}")
                text_parts.append(interview.to_text())
                text_parts.append("\n---")
        else:
            text_parts.append("（无采访记录）\n\n---")
        text_parts.append("\n### 采访摘要与核心观点")
        text_parts.append(self.summary or "（无摘要）")
        return "\n".join(text_parts)


# ── Service ────────────────────────────────────────────────────────────────────

class ZepToolsService:
    """
    Graph retrieval tools backed by PostgreSQL.

    All method signatures are identical to the old Zep-based implementation.
    """

    def __init__(self, base_url: Optional[str] = None, llm_client: Optional[LLMClient] = None):
        # base_url kept for signature compatibility — not used
        self._llm_client = llm_client
        logger.info(t("console.zepToolsInitialized"))

    @property
    def llm(self) -> LLMClient:
        if self._llm_client is None:
            self._llm_client = LLMClient()
        return self._llm_client

    # ── Base data access ───────────────────────────────────────────────────────

    def get_all_nodes(self, graph_id: str) -> List[NodeInfo]:
        logger.info(t("console.fetchingAllNodes", graphId=graph_id))
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, name, labels, summary, attributes
                       FROM graph_nodes WHERE graph_id = %s ORDER BY created_at""",
                    (graph_id,),
                )
                rows = cur.fetchall()
        result = [
            NodeInfo(
                uuid=str(r[0]),
                name=r[1] or "",
                labels=r[2] or ["Entity"],
                summary=r[3] or "",
                attributes=r[4] or {},
            )
            for r in rows
        ]
        logger.info(t("console.fetchedNodes", count=len(result)))
        return result

    def get_all_edges(self, graph_id: str, include_temporal: bool = True) -> List[EdgeInfo]:
        logger.info(t("console.fetchingAllEdges", graphId=graph_id))
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
        result = [
            EdgeInfo(
                uuid=str(r[0]),
                name=r[1] or "",
                fact=r[2] or "",
                source_node_uuid=str(r[3]) if r[3] else "",
                target_node_uuid=str(r[4]) if r[4] else "",
                source_node_name=r[5] or "",
                target_node_name=r[6] or "",
                valid_at=str(r[7]) if r[7] else None,
                invalid_at=str(r[8]) if r[8] else None,
                expired_at=str(r[9]) if r[9] else None,
                created_at=str(r[10]) if r[10] else None,
            )
            for r in rows
        ]
        logger.info(t("console.fetchedEdges", count=len(result)))
        return result

    def get_node_detail(self, node_uuid: str) -> Optional[NodeInfo]:
        logger.info(t("console.fetchingNodeDetail", uuid=node_uuid[:8]))
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name, labels, summary, attributes FROM graph_nodes WHERE id = %s",
                    (node_uuid,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return NodeInfo(
            uuid=str(row[0]),
            name=row[1] or "",
            labels=row[2] or ["Entity"],
            summary=row[3] or "",
            attributes=row[4] or {},
        )

    def get_node_edges(self, graph_id: str, node_uuid: str) -> List[EdgeInfo]:
        logger.info(t("console.fetchingNodeEdges", uuid=node_uuid[:8]))
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, name, fact, source_node_id, target_node_id,
                              source_node_name, target_node_name,
                              valid_at, invalid_at, expired_at, created_at
                       FROM graph_edges
                       WHERE graph_id = %s
                         AND (source_node_id = %s OR target_node_id = %s)
                       ORDER BY created_at""",
                    (graph_id, node_uuid, node_uuid),
                )
                rows = cur.fetchall()
        result = [
            EdgeInfo(
                uuid=str(r[0]),
                name=r[1] or "",
                fact=r[2] or "",
                source_node_uuid=str(r[3]) if r[3] else "",
                target_node_uuid=str(r[4]) if r[4] else "",
                source_node_name=r[5] or "",
                target_node_name=r[6] or "",
                valid_at=str(r[7]) if r[7] else None,
                invalid_at=str(r[8]) if r[8] else None,
                expired_at=str(r[9]) if r[9] else None,
                created_at=str(r[10]) if r[10] else None,
            )
            for r in rows
        ]
        logger.info(t("console.foundNodeEdges", count=len(result)))
        return result

    def get_entities_by_type(self, graph_id: str, entity_type: str) -> List[NodeInfo]:
        logger.info(t("console.fetchingEntitiesByType", type=entity_type))
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, name, labels, summary, attributes
                       FROM graph_nodes
                       WHERE graph_id = %s AND labels @> %s::jsonb""",
                    (graph_id, f'["{entity_type}"]'),
                )
                rows = cur.fetchall()
        result = [
            NodeInfo(
                uuid=str(r[0]),
                name=r[1] or "",
                labels=r[2] or ["Entity"],
                summary=r[3] or "",
                attributes=r[4] or {},
            )
            for r in rows
        ]
        logger.info(t("console.foundEntitiesByType", count=len(result), type=entity_type))
        return result

    # ── Search ─────────────────────────────────────────────────────────────────

    def search_graph(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
    ) -> SearchResult:
        """Keyword search across edges and/or nodes using PostgreSQL ILIKE."""
        logger.info(t("console.graphSearch", graphId=graph_id, query=query[:50]))

        keywords = [w.strip() for w in query.lower().replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]
        facts: List[str] = []
        edges_out: List[Dict[str, Any]] = []
        nodes_out: List[Dict[str, Any]] = []

        if scope in ("edges", "both"):
            all_edges = self.get_all_edges(graph_id)
            scored = []
            for edge in all_edges:
                score = self._kw_score(edge.fact + " " + edge.name, query.lower(), keywords)
                if score > 0:
                    scored.append((score, edge))
            scored.sort(key=lambda x: x[0], reverse=True)
            for _, edge in scored[:limit]:
                if edge.fact:
                    facts.append(edge.fact)
                edges_out.append({
                    "uuid": edge.uuid,
                    "name": edge.name,
                    "fact": edge.fact,
                    "source_node_uuid": edge.source_node_uuid,
                    "target_node_uuid": edge.target_node_uuid,
                })

        if scope in ("nodes", "both"):
            all_nodes = self.get_all_nodes(graph_id)
            scored_nodes = []
            for node in all_nodes:
                score = self._kw_score(node.name + " " + node.summary, query.lower(), keywords)
                if score > 0:
                    scored_nodes.append((score, node))
            scored_nodes.sort(key=lambda x: x[0], reverse=True)
            for _, node in scored_nodes[:limit]:
                nodes_out.append({
                    "uuid": node.uuid,
                    "name": node.name,
                    "labels": node.labels,
                    "summary": node.summary,
                })
                if node.summary:
                    facts.append(f"[{node.name}]: {node.summary}")

        logger.info(t("console.searchComplete", count=len(facts)))
        return SearchResult(facts=facts, edges=edges_out, nodes=nodes_out, query=query, total_count=len(facts))

    @staticmethod
    def _kw_score(text: str, query_lower: str, keywords: List[str]) -> int:
        if not text:
            return 0
        text_lower = text.lower()
        if query_lower in text_lower:
            return 100
        return sum(10 for kw in keywords if kw in text_lower)

    # ── High-level tools ───────────────────────────────────────────────────────

    def get_entity_summary(self, graph_id: str, entity_name: str) -> Dict[str, Any]:
        logger.info(t("console.fetchingEntitySummary", name=entity_name))
        search_result = self.search_graph(graph_id=graph_id, query=entity_name, limit=20)
        all_nodes = self.get_all_nodes(graph_id)
        entity_node = next((n for n in all_nodes if n.name.lower() == entity_name.lower()), None)
        related_edges = self.get_node_edges(graph_id, entity_node.uuid) if entity_node else []
        return {
            "entity_name": entity_name,
            "entity_info": entity_node.to_dict() if entity_node else None,
            "related_facts": search_result.facts,
            "related_edges": [e.to_dict() for e in related_edges],
            "total_relations": len(related_edges),
        }

    def get_graph_statistics(self, graph_id: str) -> Dict[str, Any]:
        logger.info(t("console.fetchingGraphStats", graphId=graph_id))
        nodes = self.get_all_nodes(graph_id)
        edges = self.get_all_edges(graph_id)
        entity_types: Dict[str, int] = {}
        for node in nodes:
            for label in node.labels:
                if label not in ("Entity", "Node"):
                    entity_types[label] = entity_types.get(label, 0) + 1
        relation_types: Dict[str, int] = {}
        for edge in edges:
            relation_types[edge.name] = relation_types.get(edge.name, 0) + 1
        return {
            "graph_id": graph_id,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "entity_types": entity_types,
            "relation_types": relation_types,
        }

    def get_simulation_context(self, graph_id: str, simulation_requirement: str, limit: int = 30) -> Dict[str, Any]:
        logger.info(t("console.fetchingSimContext", requirement=simulation_requirement[:50]))
        search_result = self.search_graph(graph_id=graph_id, query=simulation_requirement, limit=limit)
        stats = self.get_graph_statistics(graph_id)
        all_nodes = self.get_all_nodes(graph_id)
        entities = []
        for node in all_nodes:
            custom_labels = [l for l in node.labels if l not in ("Entity", "Node")]
            if custom_labels:
                entities.append({"name": node.name, "type": custom_labels[0], "summary": node.summary})
        return {
            "simulation_requirement": simulation_requirement,
            "related_facts": search_result.facts,
            "graph_statistics": stats,
            "entities": entities[:limit],
            "total_entities": len(entities),
        }

    # ── InsightForge ───────────────────────────────────────────────────────────

    def insight_forge(
        self,
        graph_id: str,
        query: str,
        simulation_requirement: str,
        report_context: str = "",
        max_sub_queries: int = 5,
    ) -> InsightForgeResult:
        logger.info(t("console.insightForgeStart", query=query[:50]))

        result = InsightForgeResult(
            query=query,
            simulation_requirement=simulation_requirement,
            sub_queries=[],
        )

        sub_queries = self._generate_sub_queries(query, simulation_requirement, report_context, max_sub_queries)
        result.sub_queries = sub_queries

        all_facts: List[str] = []
        all_edges: List[Dict[str, Any]] = []
        seen_facts: set = set()

        for sub_query in sub_queries:
            sr = self.search_graph(graph_id=graph_id, query=sub_query, limit=15, scope="edges")
            for fact in sr.facts:
                if fact not in seen_facts:
                    all_facts.append(fact)
                    seen_facts.add(fact)
            all_edges.extend(sr.edges)

        main_search = self.search_graph(graph_id=graph_id, query=query, limit=20, scope="edges")
        for fact in main_search.facts:
            if fact not in seen_facts:
                all_facts.append(fact)
                seen_facts.add(fact)

        result.semantic_facts = all_facts
        result.total_facts = len(all_facts)

        entity_uuids = set()
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                if edge_data.get("source_node_uuid"):
                    entity_uuids.add(edge_data["source_node_uuid"])
                if edge_data.get("target_node_uuid"):
                    entity_uuids.add(edge_data["target_node_uuid"])

        entity_insights = []
        node_map: Dict[str, NodeInfo] = {}
        for uuid in entity_uuids:
            if not uuid:
                continue
            try:
                node = self.get_node_detail(uuid)
                if node:
                    node_map[uuid] = node
                    entity_type = next((l for l in node.labels if l not in ("Entity", "Node")), "实体")
                    related_facts = [f for f in all_facts if node.name.lower() in f.lower()]
                    entity_insights.append({
                        "uuid": node.uuid,
                        "name": node.name,
                        "type": entity_type,
                        "summary": node.summary,
                        "related_facts": related_facts,
                    })
            except Exception as e:
                logger.debug(f"Failed to get node {uuid}: {e}")

        result.entity_insights = entity_insights
        result.total_entities = len(entity_insights)

        relationship_chains = []
        for edge_data in all_edges:
            if isinstance(edge_data, dict):
                src_uuid = edge_data.get("source_node_uuid", "")
                tgt_uuid = edge_data.get("target_node_uuid", "")
                rel_name = edge_data.get("name", "")
                src_name = node_map.get(src_uuid, NodeInfo('', '', [], '', {})).name or src_uuid[:8]
                tgt_name = node_map.get(tgt_uuid, NodeInfo('', '', [], '', {})).name or tgt_uuid[:8]
                chain = f"{src_name} --[{rel_name}]--> {tgt_name}"
                if chain not in relationship_chains:
                    relationship_chains.append(chain)

        result.relationship_chains = relationship_chains
        result.total_relationships = len(relationship_chains)
        logger.info(t("console.insightForgeComplete", facts=result.total_facts, entities=result.total_entities, relationships=result.total_relationships))
        return result

    def _generate_sub_queries(self, query: str, simulation_requirement: str, report_context: str = "", max_queries: int = 5) -> List[str]:
        system_prompt = """你是一个专业的问题分析专家。你的任务是将一个复杂问题分解为多个可以在模拟世界中独立观察的子问题。

要求：
1. 每个子问题应该足够具体，可以在模拟世界中找到相关的Agent行为或事件
2. 子问题应该覆盖原问题的不同维度（如：谁、什么、为什么、怎么样、何时、何地）
3. 子问题应该与模拟场景相关
4. 返回JSON格式：{"sub_queries": ["子问题1", "子问题2", ...]}"""

        user_prompt = f"""模拟需求背景：
{simulation_requirement}

{f"报告上下文：{report_context[:500]}" if report_context else ""}

请将以下问题分解为{max_queries}个子问题：
{query}

返回JSON格式的子问题列表。"""

        try:
            response = self.llm.chat_json(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.3,
            )
            sub_queries = response.get("sub_queries", [])
            return [str(sq) for sq in sub_queries[:max_queries]]
        except Exception as e:
            logger.warning(t("console.generateSubQueriesFailed", error=str(e)))
            return [query, f"{query} 的主要参与者", f"{query} 的原因和影响", f"{query} 的发展过程"][:max_queries]

    # ── PanoramaSearch ─────────────────────────────────────────────────────────

    def panorama_search(self, graph_id: str, query: str, include_expired: bool = True, limit: int = 50) -> PanoramaResult:
        logger.info(t("console.panoramaSearchStart", query=query[:50]))
        result = PanoramaResult(query=query)

        all_nodes = self.get_all_nodes(graph_id)
        node_map = {n.uuid: n for n in all_nodes}
        result.all_nodes = all_nodes
        result.total_nodes = len(all_nodes)

        all_edges = self.get_all_edges(graph_id, include_temporal=True)
        result.all_edges = all_edges
        result.total_edges = len(all_edges)

        active_facts: List[str] = []
        historical_facts: List[str] = []
        query_lower = query.lower()
        keywords = [w.strip() for w in query_lower.replace(',', ' ').replace('，', ' ').split() if len(w.strip()) > 1]

        for edge in all_edges:
            if not edge.fact:
                continue
            is_historical = edge.is_expired or edge.is_invalid
            if is_historical:
                valid_at = edge.valid_at or "未知"
                invalid_at = edge.invalid_at or edge.expired_at or "未知"
                historical_facts.append(f"[{valid_at} - {invalid_at}] {edge.fact}")
            else:
                active_facts.append(edge.fact)

        def relevance_score(fact: str) -> int:
            fl = fact.lower()
            score = 100 if query_lower in fl else 0
            score += sum(10 for kw in keywords if kw in fl)
            return score

        active_facts.sort(key=relevance_score, reverse=True)
        historical_facts.sort(key=relevance_score, reverse=True)
        result.active_facts = active_facts[:limit]
        result.historical_facts = historical_facts[:limit] if include_expired else []
        result.active_count = len(active_facts)
        result.historical_count = len(historical_facts)
        logger.info(t("console.panoramaSearchComplete", active=result.active_count, historical=result.historical_count))
        return result

    # ── QuickSearch ────────────────────────────────────────────────────────────

    def quick_search(self, graph_id: str, query: str, limit: int = 10) -> SearchResult:
        logger.info(t("console.quickSearchStart", query=query[:50]))
        result = self.search_graph(graph_id=graph_id, query=query, limit=limit, scope="edges")
        logger.info(t("console.quickSearchComplete", count=result.total_count))
        return result

    # ── InterviewAgents ────────────────────────────────────────────────────────

    def interview_agents(
        self,
        simulation_id: str,
        interview_requirement: str,
        simulation_requirement: str = "",
        max_agents: int = 5,
        custom_questions: List[str] = None,
    ) -> InterviewResult:
        from .simulation_runner import SimulationRunner

        logger.info(t("console.interviewAgentsStart", requirement=interview_requirement[:50]))
        result = InterviewResult(interview_topic=interview_requirement, interview_questions=custom_questions or [])

        profiles = self._load_agent_profiles(simulation_id)
        if not profiles:
            result.summary = "未找到可采访的Agent人设文件"
            return result

        result.total_agents = len(profiles)
        selected_agents, selected_indices, selection_reasoning = self._select_agents_for_interview(
            profiles, interview_requirement, simulation_requirement, max_agents
        )
        result.selected_agents = selected_agents
        result.selection_reasoning = selection_reasoning

        if not result.interview_questions:
            result.interview_questions = self._generate_interview_questions(
                interview_requirement, simulation_requirement, selected_agents
            )

        combined_prompt = "\n".join([f"{i+1}. {q}" for i, q in enumerate(result.interview_questions)])
        INTERVIEW_PROMPT_PREFIX = (
            "你正在接受一次采访。请结合你的人设、所有的过往记忆与行动，"
            "以纯文本方式直接回答以下问题。\n"
            "回复要求：\n"
            "1. 直接用自然语言回答，不要调用任何工具\n"
            "2. 不要返回JSON格式或工具调用格式\n"
            "3. 不要使用Markdown标题（如#、##、###）\n"
            "4. 按问题编号逐一回答，每个回答以「问题X：」开头（X为问题编号）\n"
            "5. 每个问题的回答之间用空行分隔\n"
            "6. 回答要有实质内容，每个问题至少回答2-3句话\n\n"
        )
        optimized_prompt = f"{INTERVIEW_PROMPT_PREFIX}{combined_prompt}"

        try:
            interviews_request = [
                {"agent_id": agent_idx, "prompt": optimized_prompt}
                for agent_idx in selected_indices
            ]
            api_result = SimulationRunner.interview_agents_batch(
                simulation_id=simulation_id,
                interviews=interviews_request,
                platform=None,
                timeout=180.0,
            )
            if not api_result.get("success", False):
                result.summary = f"采访API调用失败：{api_result.get('error', '未知错误')}"
                return result

            api_data = api_result.get("result", {})
            results_dict = api_data.get("results", {}) if isinstance(api_data, dict) else {}

            for i, agent_idx in enumerate(selected_indices):
                agent = selected_agents[i]
                agent_name = agent.get("realname", agent.get("username", f"Agent_{agent_idx}"))
                agent_role = agent.get("profession", "未知")
                agent_bio = agent.get("bio", "")

                twitter_response = self._clean_tool_call_response(results_dict.get(f"twitter_{agent_idx}", {}).get("response", ""))
                reddit_response = self._clean_tool_call_response(results_dict.get(f"reddit_{agent_idx}", {}).get("response", ""))

                twitter_text = twitter_response or "（该平台未获得回复）"
                reddit_text = reddit_response or "（该平台未获得回复）"
                response_text = f"【Twitter平台回答】\n{twitter_text}\n\n【Reddit平台回答】\n{reddit_text}"

                combined_responses = f"{twitter_response} {reddit_response}"
                clean_text = re.sub(r'#{1,6}\s+', '', combined_responses)
                clean_text = re.sub(r'\{[^}]*tool_name[^}]*\}', '', clean_text)
                clean_text = re.sub(r'[*_`|>~\-]{2,}', '', clean_text)
                clean_text = re.sub(r'问题\d+[：:]\s*', '', clean_text)
                clean_text = re.sub(r'【[^】]+】', '', clean_text)

                sentences = re.split(r'[。！？]', clean_text)
                meaningful = [
                    s.strip() for s in sentences
                    if 20 <= len(s.strip()) <= 150
                    and not re.match(r'^[\s\W，,；;：:、]+', s.strip())
                    and not s.strip().startswith(('{', '问题'))
                ]
                meaningful.sort(key=len, reverse=True)
                key_quotes = [s + "。" for s in meaningful[:3]]

                if not key_quotes:
                    paired = re.findall(r'“([^“”]{15,100})”', clean_text)
                    paired += re.findall(r'「([^「」]{15,100})」', clean_text)
                    key_quotes = [q for q in paired if not re.match(r'^[，,；;：:、]', q)][:3]

                result.interviews.append(AgentInterview(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    agent_bio=agent_bio[:1000],
                    question=combined_prompt,
                    response=response_text,
                    key_quotes=key_quotes[:5],
                ))

            result.interviewed_count = len(result.interviews)

        except ValueError as e:
            result.summary = f"采访失败：{str(e)}。模拟环境可能已关闭。"
            return result
        except Exception as e:
            logger.error(f"Interview error: {e}")
            result.summary = f"采访过程发生错误：{str(e)}"
            return result

        if result.interviews:
            result.summary = self._generate_interview_summary(result.interviews, interview_requirement)

        logger.info(t("console.interviewAgentsComplete", count=result.interviewed_count))
        return result

    @staticmethod
    def _clean_tool_call_response(response: str) -> str:
        if not response or not response.strip().startswith('{'):
            return response
        text = response.strip()
        if 'tool_name' not in text[:80]:
            return response
        try:
            data = json.loads(text)
            if isinstance(data, dict) and 'arguments' in data:
                for key in ('content', 'text', 'body', 'message', 'reply'):
                    if key in data['arguments']:
                        return str(data['arguments'][key])
        except (json.JSONDecodeError, KeyError, TypeError):
            match = re.search(r'"content"\s*:\s*"((?:[^"\\]|\\.)*)"', text)
            if match:
                return match.group(1).replace('\\n', '\n').replace('\\"', '"')
        return response

    def _load_agent_profiles(self, simulation_id: str) -> List[Dict[str, Any]]:
        import os
        import csv
        sim_dir = os.path.join(os.path.dirname(__file__), f'../../uploads/simulations/{simulation_id}')
        profiles = []
        reddit_profile_path = os.path.join(sim_dir, "reddit_profiles.json")
        if os.path.exists(reddit_profile_path):
            try:
                with open(reddit_profile_path, 'r', encoding='utf-8') as f:
                    profiles = json.load(f)
                logger.info(t("console.loadedRedditProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readRedditProfilesFailed", error=e))
        twitter_profile_path = os.path.join(sim_dir, "twitter_profiles.csv")
        if os.path.exists(twitter_profile_path):
            try:
                with open(twitter_profile_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        profiles.append({
                            "realname": row.get("name", ""),
                            "username": row.get("username", ""),
                            "bio": row.get("description", ""),
                            "persona": row.get("user_char", ""),
                            "profession": "未知",
                        })
                logger.info(t("console.loadedTwitterProfiles", count=len(profiles)))
                return profiles
            except Exception as e:
                logger.warning(t("console.readTwitterProfilesFailed", error=e))
        return profiles

    def _select_agents_for_interview(self, profiles, interview_requirement, simulation_requirement, max_agents):
        agent_summaries = [
            {
                "index": i,
                "name": p.get("realname", p.get("username", f"Agent_{i}")),
                "profession": p.get("profession", "未知"),
                "bio": p.get("bio", "")[:200],
                "interested_topics": p.get("interested_topics", []),
            }
            for i, p in enumerate(profiles)
        ]
        system_prompt = """你是一个专业的采访策划专家。你的任务是根据采访需求，从模拟Agent列表中选择最适合采访的对象。

返回JSON格式：
{
    "selected_indices": [选中Agent的索引列表],
    "reasoning": "选择理由说明"
}"""
        user_prompt = f"""采访需求：{interview_requirement}

模拟背景：{simulation_requirement or "未提供"}

可选择的Agent列表（共{len(agent_summaries)}个）：
{json.dumps(agent_summaries, ensure_ascii=False, indent=2)}

请选择最多{max_agents}个最适合采访的Agent，并说明选择理由。"""
        try:
            response = self.llm.chat_json(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.3,
            )
            selected_indices = response.get("selected_indices", [])[:max_agents]
            reasoning = response.get("reasoning", "基于相关性自动选择")
            selected_agents = []
            valid_indices = []
            for idx in selected_indices:
                if 0 <= idx < len(profiles):
                    selected_agents.append(profiles[idx])
                    valid_indices.append(idx)
            return selected_agents, valid_indices, reasoning
        except Exception as e:
            logger.warning(t("console.llmSelectAgentFailed", error=e))
            selected = profiles[:max_agents]
            indices = list(range(min(max_agents, len(profiles))))
            return selected, indices, "使用默认选择策略"

    def _generate_interview_questions(self, interview_requirement, simulation_requirement, selected_agents):
        agent_roles = [a.get("profession", "未知") for a in selected_agents]
        system_prompt = """你是一个专业的记者/采访者。根据采访需求，生成3-5个深度采访问题。

返回JSON格式：{"questions": ["问题1", "问题2", ...]}"""
        user_prompt = f"""采访需求：{interview_requirement}

模拟背景：{simulation_requirement or "未提供"}

采访对象角色：{', '.join(agent_roles)}

请生成3-5个采访问题。"""
        try:
            response = self.llm.chat_json(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.5,
            )
            return response.get("questions", [f"关于{interview_requirement}，您有什么看法？"])
        except Exception as e:
            logger.warning(t("console.generateInterviewQuestionsFailed", error=e))
            return [f"关于{interview_requirement}，您的观点是什么？", "这件事对您或您所代表的群体有什么影响？", "您认为应该如何解决或改进这个问题？"]

    def _generate_interview_summary(self, interviews, interview_requirement):
        if not interviews:
            return "未完成任何采访"
        interview_texts = [f"【{iv.agent_name}（{iv.agent_role}）】\n{iv.response[:500]}" for iv in interviews]
        quote_instruction = "引用受访者原话时使用中文引号「」" if get_locale() == 'zh' else 'Use quotation marks "" when quoting interviewees'
        system_prompt = f"""你是一个专业的新闻编辑。请根据多位受访者的回答，生成一份采访摘要。

格式约束（必须遵守）：
- 使用纯文本段落，用空行分隔不同部分
- 不要使用Markdown标题（如#、##、###）
- {quote_instruction}"""
        user_prompt = f"""采访主题：{interview_requirement}

采访内容：
{"".join(interview_texts)}

请生成采访摘要。"""
        try:
            return self.llm.chat(
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.3,
                max_tokens=800,
            )
        except Exception as e:
            logger.warning(t("console.generateInterviewSummaryFailed", error=e))
            return "\n".join([f"• {iv.agent_name}: {iv.response[:100]}..." for iv in interviews])
