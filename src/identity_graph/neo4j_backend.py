"""
Neo4j-backed graph backend — persists identity graphs across restarts and
lets multiple analysts query the same case data. Requires a running Neo4j
instance (see docker-compose.yml) and NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD
set in .env.

Nodes are labeled `:Alias` (scoped to a case via a `case_id` property, so
multiple cases can share one Neo4j instance without colliding). Edges are
`:CORRELATED_WITH` relationships carrying `types` and `confidence`.
"""

import os
from typing import Dict

import networkx as nx
from neo4j import GraphDatabase

from src.identity_graph.graph_backend import GraphBackend


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

    def add_alias(self, case_id: str, alias: str, **attrs) -> None:
        with self._driver.session() as session:
            session.run(
                "MERGE (a:Alias {case_id: $case_id, name: $alias}) "
                "SET a += $attrs",
                case_id=case_id, alias=alias, attrs=attrs,
            )

    def add_correlation(
        self, case_id: str, alias_a: str, alias_b: str, corr_type: str, confidence: float
    ) -> None:
        with self._driver.session() as session:
            session.run(
                """
                MERGE (a:Alias {case_id: $case_id, name: $alias_a})
                MERGE (b:Alias {case_id: $case_id, name: $alias_b})
                MERGE (a)-[r:CORRELATED_WITH]-(b)
                ON CREATE SET r.types = [$corr_type], r.confidence = $confidence
                ON MATCH SET
                    r.types = CASE WHEN $corr_type IN r.types THEN r.types ELSE r.types + $corr_type END,
                    r.confidence = CASE WHEN $confidence > r.confidence THEN $confidence ELSE r.confidence END
                """,
                case_id=case_id, alias_a=alias_a, alias_b=alias_b,
                corr_type=corr_type, confidence=confidence,
            )

    def to_json(self, case_id: str) -> Dict:
        with self._driver.session() as session:
            node_records = session.run(
                "MATCH (a:Alias {case_id: $case_id}) RETURN a.name AS name",
                case_id=case_id,
            )
            nodes = [{"id": r["name"], "type": "alias"} for r in node_records]

            edge_records = session.run(
                """
                MATCH (a:Alias {case_id: $case_id})-[r:CORRELATED_WITH]-(b:Alias {case_id: $case_id})
                WHERE a.name < b.name
                RETURN a.name AS source, b.name AS target, r.types AS types, r.confidence AS confidence
                """,
                case_id=case_id,
            )
            edges = [
                {
                    "source": r["source"],
                    "target": r["target"],
                    "types": r["types"],
                    "confidence": r["confidence"],
                }
                for r in edge_records
            ]

        return {"nodes": nodes, "edges": edges}

    def get_networkx_graph(self, case_id: str) -> nx.Graph:
        """Materialize a NetworkX graph from Neo4j, for reuse by
        src/visualization/graph_viz.py without duplicating rendering logic."""
        data = self.to_json(case_id)
        graph = nx.Graph()
        for node in data["nodes"]:
            graph.add_node(node["id"], type=node.get("type", "alias"))
        for edge in data["edges"]:
            graph.add_edge(
                edge["source"], edge["target"],
                types=edge["types"], confidence=edge["confidence"],
            )
        return graph
