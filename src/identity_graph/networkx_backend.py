"""
In-memory NetworkX graph backend — zero setup, resets on process restart.
Good for demos and single-session analysis; use Neo4jBackend for anything
that needs to persist across restarts or be shared by multiple analysts.
"""

from typing import Dict

import networkx as nx

from src.identity_graph.graph_backend import GraphBackend


class NetworkXBackend(GraphBackend):
    def __init__(self):
        # One graph per case_id, held in memory.
        self._graphs: Dict[str, nx.Graph] = {}

    def _get_graph(self, case_id: str) -> nx.Graph:
        if case_id not in self._graphs:
            self._graphs[case_id] = nx.Graph()
        return self._graphs[case_id]

    def add_alias(self, case_id: str, alias: str, **attrs) -> None:
        graph = self._get_graph(case_id)
        graph.add_node(alias, type="alias", **attrs)

    def add_correlation(
        self, case_id: str, alias_a: str, alias_b: str, corr_type: str, confidence: float
    ) -> None:
        graph = self._get_graph(case_id)
        if graph.has_edge(alias_a, alias_b):
            existing = graph[alias_a][alias_b]
            types = set(existing.get("types", []))
            types.add(corr_type)
            graph[alias_a][alias_b]["types"] = list(types)
            graph[alias_a][alias_b]["confidence"] = max(existing["confidence"], confidence)
        else:
            graph.add_edge(alias_a, alias_b, types=[corr_type], confidence=confidence)

    def to_json(self, case_id: str) -> Dict:
        graph = self._get_graph(case_id)
        return {
            "nodes": [{"id": n, **graph.nodes[n]} for n in graph.nodes],
            "edges": [{"source": u, "target": v, **graph[u][v]} for u, v in graph.edges],
        }

    def get_networkx_graph(self, case_id: str) -> nx.Graph:
        return self._get_graph(case_id)
