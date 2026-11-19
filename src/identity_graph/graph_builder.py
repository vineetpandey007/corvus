"""
Identity Graph Builder — orchestrates all correlation signals (stylometry,
PGP key reuse, wallet reuse, username similarity) and writes results into
whichever graph backend is configured (config/config.yaml -> graph.backend:
"networkx" for in-memory/demo use, or "neo4j" for persistent storage).
"""

from typing import Dict, List

from src.stylometry.author_matcher import compare_authors
from src.identity_graph.pgp_correlator import correlate as pgp_correlate
from src.identity_graph.pgp_correlator import extract_wallet_addresses
from src.identity_graph.username_matcher import compare_usernames
from src.identity_graph.networkx_backend import NetworkXBackend
from src.identity_graph.graph_backend import GraphBackend
from src.utils.config import load_config
from src.utils.logger import get_logger, audit_log

logger = get_logger()

_backend_singleton: GraphBackend | None = None


def get_backend() -> GraphBackend:
    """
    Return the configured graph backend as a process-wide singleton so
    in-memory (NetworkX) data survives across requests within one running
    API process, and so a single Neo4j driver/connection pool is reused.
    """
    global _backend_singleton
    if _backend_singleton is not None:
        return _backend_singleton

    cfg = load_config()
    backend_name = cfg.get("graph", {}).get("backend", "networkx")

    if backend_name == "neo4j":
        from src.identity_graph.neo4j_backend import Neo4jBackend
        _backend_singleton = Neo4jBackend()
    else:
        _backend_singleton = NetworkXBackend()

    return _backend_singleton


class IdentityGraphBuilder:
    def __init__(self, case_id: str = "default", backend: GraphBackend | None = None):
        self.case_id = case_id
        self.backend = backend or get_backend()

    def add_alias(self, alias: str, **attrs):
        self.backend.add_alias(self.case_id, alias, **attrs)

    def add_correlation(self, alias_a: str, alias_b: str, corr_type: str, confidence: float):
        self.backend.add_correlation(self.case_id, alias_a, alias_b, corr_type, confidence)

    def build_from_posts(self, posts: List[Dict], actor: str = "system") -> "IdentityGraphBuilder":
        """
        Run all correlation modules pairwise across a list of posts and
        write the resulting correlations into the configured backend.

        posts: list of {"alias": str, "text": str, ...}
        Returns self, so callers can chain .to_json() / .get_networkx_graph().
        """
        cfg = load_config()
        username_enabled = cfg.get("username", {}).get("enabled", True)

        for post in posts:
            self.add_alias(post["alias"])

        n = len(posts)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = posts[i], posts[j]
                if a["alias"] == b["alias"]:
                    continue

                # 1. Stylometry
                style_result = compare_authors(a["text"], b["text"])
                if style_result.get("likely_same_author"):
                    self.add_correlation(
                        a["alias"], b["alias"], "stylometry", style_result["similarity_score"]
                    )

                # 2. PGP key reuse
                pgp_result = pgp_correlate(a["text"], b["text"])
                if pgp_result["match"]:
                    self.add_correlation(
                        a["alias"], b["alias"], "pgp_key_reuse", pgp_result["confidence"]
                    )

                # 3. Wallet address reuse (address appearing in both posts' text)
                wallets_a = set(extract_wallet_addresses(a["text"]))
                wallets_b = set(extract_wallet_addresses(b["text"]))
                if wallets_a & wallets_b:
                    self.add_correlation(a["alias"], b["alias"], "wallet_reuse", 0.9)

                # 4. Username similarity (weak signal, capped confidence — see username_matcher.py)
                if username_enabled:
                    uname_result = compare_usernames(a["alias"], b["alias"])
                    if uname_result["likely_related"]:
                        self.add_correlation(
                            a["alias"], b["alias"], "username_similarity", uname_result["confidence"]
                        )

        graph_json = self.backend.to_json(self.case_id)
        audit_log(
            action="build_identity_graph",
            actor=actor,
            details={
                "case_id": self.case_id,
                "num_aliases": len(graph_json["nodes"]),
                "num_correlations": len(graph_json["edges"]),
            },
        )
        logger.info(
            f"[case={self.case_id}] Built identity graph: "
            f"{len(graph_json['nodes'])} aliases, {len(graph_json['edges'])} correlations"
        )
        return self

    def to_json(self) -> Dict:
        return self.backend.to_json(self.case_id)

    def get_networkx_graph(self):
        return self.backend.get_networkx_graph(self.case_id)
