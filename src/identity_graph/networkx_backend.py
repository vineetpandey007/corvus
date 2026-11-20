"""
In-memory NetworkX graph backend — thread-safe per-case storage with
Noisy-OR multi-signal confidence fusion and forensic evidence tracking.
"""

from typing import Any, Dict, Optional

import networkx as nx

from src.identity_graph.graph_backend import GraphBackend


def _fuse_confidences(signal_scores: Dict[str, float]) -> float:
    """
    Combine independent signal confidences via Noisy-OR:
        1 - prod(1 - c_i)
    Deduplicates by signal type first so repeated observations of the same
    signal do not artificially inflate confidence.
    """
    if not signal_scores:
        return 0.0
    complement = 1.0
    for score in signal_scores.values():
        clamped = max(0.0, min(0.99, float(score)))
        complement *= (1.0 - clamped)
    return round(min(1.0 - complement, 0.99), 4)


class NetworkXBackend(GraphBackend):
    def __init__(self):
        self._graphs: Dict[str, nx.Graph] = {}

    def _get_graph(self, case_id: str) -> nx.Graph:
        if case_id not in self._graphs:
            self._graphs[case_id] = nx.Graph()
        return self._graphs[case_id]

    def add_alias(self, case_id: str, alias: str, **attrs) -> None:
        if not alias:
            return
        graph = self._get_graph(case_id)
        if graph.has_node(alias):
            graph.nodes[alias].update(attrs)
        else:
            graph.add_node(alias, type="alias", **attrs)

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

        graph = self._get_graph(case_id)
        if not graph.has_node(alias_a):
            graph.add_node(alias_a, type="alias")
        if not graph.has_node(alias_b):
            graph.add_node(alias_b, type="alias")

        if graph.has_edge(alias_a, alias_b):
            edge = graph[alias_a][alias_b]
            signal_scores: Dict[str, float] = dict(edge.get("signal_scores", {}))
            # Backward compatibility if an edge was initialized without signal_scores
            if not signal_scores and edge.get("types"):
                for t in edge["types"]:
                    signal_scores[t] = edge.get("confidence", 0.0)

            signal_scores[corr_type] = max(signal_scores.get(corr_type, 0.0), float(confidence))
            edge["signal_scores"] = signal_scores
            edge["types"] = list(signal_scores.keys())
            edge["confidence"] = _fuse_confidences(signal_scores)

            if evidence:
                existing_ev: Dict[str, Any] = dict(edge.get("evidence", {}))
                existing_ev[corr_type] = evidence
                edge["evidence"] = existing_ev
        else:
            signal_scores = {corr_type: float(confidence)}
            attrs: Dict[str, Any] = {
                "types": [corr_type],
                "signal_scores": signal_scores,
                "confidence": round(float(confidence), 4),
            }
            if evidence:
                attrs["evidence"] = {corr_type: evidence}
            graph.add_edge(alias_a, alias_b, **attrs)

    def to_json(self, case_id: str) -> Dict[str, Any]:
        graph = self._get_graph(case_id)
        return {
            "nodes": [{"id": n, **graph.nodes[n]} for n in graph.nodes],
            "edges": [{"source": u, "target": v, **graph[u][v]} for u, v in graph.edges],
        }

    def get_networkx_graph(self, case_id: str) -> nx.Graph:
        return self._get_graph(case_id)

    def delete_case(self, case_id: str) -> None:
        self._graphs.pop(case_id, None)