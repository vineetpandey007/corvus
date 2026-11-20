"""
Neo4j-backed graph backend — persists identity graphs across restarts with
canonical edge MERGE, Noisy-OR multi-signal confidence fusion, and serialized
forensic evidence payloads.
"""

import json
import os
from typing import Any, Dict, Optional

import networkx as nx
from neo4j import GraphDatabase

from src.identity_graph.graph_backend import GraphBackend
from src.identity_graph.networkx_backend import _fuse_confidences


class Neo4jBackend(GraphBackend):
    def __init__(self):
        uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD")
        if not password:
            raise RuntimeError(
                "NEO4J_PASSWORD is not set. Configure Neo4j credentials in .env, "
                "or set config/config.yaml -> graph.backend: networkx to use the "
                "in-memory backend instead."
            )
        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._ensure_constraints()

    def close(self):
        self._driver.close()

    def _ensure_constraints(self):
        with self._driver.session() as session:
            session.run(
                "CREATE CONSTRAINT alias_unique IF NOT EXISTS "
                "FOR (a:Alias) REQUIRE (a.case_id, a.name) IS UNIQUE"
            )

    @staticmethod
    def _sanitize_props(attrs: Dict[str, Any]) -> Dict[str, Any]:
        """Convert non-primitive dicts into JSON strings for Neo4j property compatibility."""
        clean: Dict[str, Any] = {}
        for k, v in attrs.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                clean[k] = v
            elif isinstance(v, (list, tuple)) and all(
                isinstance(i, (str, int, float, bool)) for i in v
            ):
                clean[k] = list(v)
            else:
                clean[f"{k}_json"] = json.dumps(v)
        return clean

    def add_alias(self, case_id: str, alias: str, **attrs) -> None:
        if not alias:
            return
        clean_attrs = self._sanitize_props(attrs)
        with self._driver.session() as session:
            session.run(
                "MERGE (a:Alias {case_id: $case_id, name: $alias}) "
                "SET a += $attrs",
                case_id=case_id,
                alias=alias,
                attrs=clean_attrs,
            )

    def add_correlation(
        self,
        case_id: str,
        alias_a: str,
        alias_b: str,
        corr_type: str,
        confidence: float,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not alias_a or not alias_b or alias_a == alias_b:
            return

        # Canonical endpoint ordering prevents duplicate bidirectional relationships
        u, v = sorted([alias_a, alias_b])

        with self._driver.session() as session:
            rec = session.run(
                """
                MERGE (a:Alias {case_id: $case_id, name: $u})
                MERGE (b:Alias {case_id: $case_id, name: $v})
                MERGE (a)-[r:CORRELATED_WITH]->(b)
                RETURN r.signal_scores_json AS scores_json,
                       r.evidence_json AS evidence_json,
                       r.types AS types,
                       r.confidence AS confidence
                """,
                case_id=case_id,
                u=u,
                v=v,
            ).single()

            signal_scores: Dict[str, float] = {}
            if rec and rec["scores_json"]:
                signal_scores = json.loads(rec["scores_json"])
            elif rec and rec["types"]:
                for t in rec["types"]:
                    signal_scores[t] = float(rec["confidence"] or 0.0)

            signal_scores[corr_type] = max(signal_scores.get(corr_type, 0.0), float(confidence))
            fused = _fuse_confidences(signal_scores) if len(signal_scores) > 1 else round(float(confidence), 4)

            existing_ev: Dict[str, Any] = {}
            if rec and rec["evidence_json"]:
                existing_ev = json.loads(rec["evidence_json"])
            if evidence:
                existing_ev[corr_type] = evidence

            session.run(
                """
                MATCH (a:Alias {case_id: $case_id, name: $u})-[r:CORRELATED_WITH]->(b:Alias {case_id: $case_id, name: $v})
                SET r.types = $types,
                    r.confidence = $confidence,
                    r.signal_scores_json = $scores_json,
                    r.evidence_json = $evidence_json
                """,
                case_id=case_id,
                u=u,
                v=v,
                types=list(signal_scores.keys()),
                confidence=fused,
                scores_json=json.dumps(signal_scores),
                evidence_json=json.dumps(existing_ev) if existing_ev else None,
            )

    def to_json(self, case_id: str) -> Dict[str, Any]:
        with self._driver.session() as session:
            node_records = session.run(
                "MATCH (a:Alias {case_id: $case_id}) RETURN a.name AS name, properties(a) AS props",
                case_id=case_id,
            )
            nodes = []
            for r in node_records:
                props = dict(r["props"] or {})
                props.pop("case_id", None)
                props.pop("name", None)
                nodes.append({"id": r["name"], "type": "alias", **props})

            edge_records = session.run(
                """
                MATCH (a:Alias {case_id: $case_id})-[r:CORRELATED_WITH]->(b:Alias {case_id: $case_id})
                RETURN a.name AS source,
                       b.name AS target,
                       r.types AS types,
                       r.confidence AS confidence,
                       r.signal_scores_json AS scores_json,
                       r.evidence_json AS evidence_json
                """,
                case_id=case_id,
            )
            edges = []
            for r in edge_records:
                edge: Dict[str, Any] = {
                    "source": r["source"],
                    "target": r["target"],
                    "types": r["types"] or [],
                    "confidence": r["confidence"],
                }
                if r["scores_json"]:
                    edge["signal_scores"] = json.loads(r["scores_json"])
                if r["evidence_json"]:
                    edge["evidence"] = json.loads(r["evidence_json"])
                edges.append(edge)

        return {"nodes": nodes, "edges": edges}

    def get_networkx_graph(self, case_id: str) -> nx.Graph:
        """Materialize a NetworkX graph from Neo4j for shared visualization/reporting."""
        data = self.to_json(case_id)
        graph = nx.Graph()
        for node in data["nodes"]:
            node_copy = dict(node)
            nid = node_copy.pop("id")
            graph.add_node(nid, **node_copy)
        for edge in data["edges"]:
            edge_copy = dict(edge)
            src = edge_copy.pop("source")
            dst = edge_copy.pop("target")
            graph.add_edge(src, dst, **edge_copy)
        return graph

    def delete_case(self, case_id: str) -> None:
        with self._driver.session() as session:
            session.run(
                "MATCH (a:Alias {case_id: $case_id}) DETACH DELETE a",
                case_id=case_id,
            )