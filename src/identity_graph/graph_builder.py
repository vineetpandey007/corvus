"""
Identity Graph Builder — orchestrates multi-signal attribution (stylometry,
OpenPGP key/UID reuse, multi-chain wallet reuse, username similarity) in O(N)
extraction time and persists forensic evidence into the configured backend.
"""

import threading
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from src.blockchain.wallet_tracer import extract_wallet_addresses_typed
from src.identity_graph.graph_backend import GraphBackend
from src.identity_graph.networkx_backend import NetworkXBackend
from src.identity_graph.pgp_correlator import extract_all_pgp_blocks, parse_pgp_public_key
from src.identity_graph.username_matcher import compare_usernames
from src.stylometry.author_matcher import compare_profiles
from src.stylometry.feature_extractor import extract_features
from src.utils.config import load_config
from src.utils.logger import audit_log, get_logger

logger = get_logger()

_backend_singleton: Optional[GraphBackend] = None
_backend_lock = threading.Lock()


def get_backend() -> GraphBackend:
    """Thread-safe process-wide graph backend singleton."""
    global _backend_singleton
    if _backend_singleton is not None:
        return _backend_singleton

    with _backend_lock:
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


def reset_backend() -> None:
    """Reset the backend singleton (useful for tests or runtime reconfiguration)."""
    global _backend_singleton
    with _backend_lock:
        _backend_singleton = None


class IdentityGraphBuilder:
    def __init__(self, case_id: str = "default", backend: Optional[GraphBackend] = None):
        self.case_id = case_id
        self.backend = backend or get_backend()

    def add_alias(self, alias: str, **attrs) -> None:
        self.backend.add_alias(self.case_id, alias, **attrs)

    def add_correlation(
        self,
        alias_a: str,
        alias_b: str,
        corr_type: str,
        confidence: float,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.backend.add_correlation(
            self.case_id, alias_a, alias_b, corr_type, confidence, evidence=evidence
        )

    def build_from_posts(self, posts: List[Dict], actor: str = "system") -> "IdentityGraphBuilder":
        """
        Pre-extract artifacts per alias in O(N_posts), then correlate unique
        aliases pairwise in O(N_aliases^2) with full forensic evidence payloads.
        """
        cfg = load_config()
        username_enabled = cfg.get("username", {}).get("enabled", True)
        stylo_cfg = cfg.get("stylometry", {})
        threshold = stylo_cfg.get("similarity_threshold", 0.75)
        min_len = stylo_cfg.get("min_text_length_chars", 200)

        # 1. Aggregate artifacts per unique alias (O(N_posts))
        alias_texts: Dict[str, List[str]] = defaultdict(list)
        alias_sources: Dict[str, Set[str]] = defaultdict(set)
        alias_wallets: Dict[str, Dict[str, str]] = defaultdict(dict)  # norm_addr -> chain
        alias_pgp_fps: Dict[str, Set[str]] = defaultdict(set)
        alias_pgp_uids: Dict[str, Set[str]] = defaultdict(set)

        for post in posts:
            alias = (post.get("alias") or "").strip()
            text = post.get("text") or ""
            if not alias:
                continue

            alias_texts[alias].append(text)
            if post.get("source"):
                alias_sources[alias].add(str(post["source"]))

            for w in extract_wallet_addresses_typed(text):
                norm_key = w["address"].lower() if w["chain"] in ("ethereum", "bitcoin") else w["address"]
                alias_wallets[alias][norm_key] = w["chain"]

            for block in extract_all_pgp_blocks(text):
                parsed = parse_pgp_public_key(block)
                if parsed:
                    alias_pgp_fps[alias].add(parsed["fingerprint"])
                    alias_pgp_fps[alias].update(parsed.get("subkey_fingerprints", []))
                    for uid in parsed.get("user_ids", []):
                        alias_pgp_uids[alias].add(uid.lower())

        aliases = list(alias_texts.keys())

        # 2. Register nodes with forensic metadata and pre-compute stylometry profiles (O(N_aliases))
        stylo_profiles: Dict[str, Dict[str, Any]] = {}
        for alias in aliases:
            combined_text = "\n\n".join(alias_texts[alias])
            self.add_alias(
                alias,
                post_count=len(alias_texts[alias]),
                sources=sorted(alias_sources[alias]),
                wallets=sorted(alias_wallets[alias].keys()),
                pgp_fingerprints=sorted(alias_pgp_fps[alias]),
            )
            if len(combined_text) >= min_len:
                stylo_profiles[alias] = extract_features(combined_text)

        # 3. Correlate unique alias pairs (O(N_aliases^2))
        m = len(aliases)
        for i in range(m):
            for j in range(i + 1, m):
                a, b = aliases[i], aliases[j]

                # Signal 1: Stylometry (over aggregated per-alias corpus)
                if a in stylo_profiles and b in stylo_profiles:
                    style_result = compare_profiles(
                        stylo_profiles[a],
                        stylo_profiles[b],
                        threshold=threshold,
                        min_len=min_len,
                    )
                    if style_result.get("likely_same_author"):
                        self.add_correlation(
                            a,
                            b,
                            "stylometry",
                            style_result["similarity_score"],
                            evidence={
                                "similarity_score": style_result["similarity_score"],
                                "breakdown": style_result.get("breakdown", {}),
                            },
                        )

                # Signal 2: OpenPGP key fingerprint or User ID reuse
                shared_fps = sorted(alias_pgp_fps[a] & alias_pgp_fps[b])
                if shared_fps:
                    self.add_correlation(
                        a,
                        b,
                        "pgp_key_reuse",
                        0.98,
                        evidence={
                            "match_reason": "exact_pgp_key_reuse",
                            "shared_fingerprints": shared_fps,
                        },
                    )
                else:
                    shared_uids = sorted(alias_pgp_uids[a] & alias_pgp_uids[b])
                    if shared_uids:
                        self.add_correlation(
                            a,
                            b,
                            "pgp_key_reuse",
                            0.80,
                            evidence={
                                "match_reason": "shared_pgp_user_id",
                                "shared_user_ids": shared_uids,
                            },
                        )

                # Signal 3: Multi-chain wallet address reuse
                shared_wallets = sorted(set(alias_wallets[a].keys()) & set(alias_wallets[b].keys()))
                if shared_wallets:
                    self.add_correlation(
                        a,
                        b,
                        "wallet_reuse",
                        0.90,
                        evidence={
                            "shared_addresses": shared_wallets,
                            "chains": sorted({alias_wallets[a][addr] for addr in shared_wallets}),
                        },
                    )

                # Signal 4: Username / handle similarity
                if username_enabled:
                    uname_result = compare_usernames(a, b)
                    if uname_result["likely_related"]:
                        self.add_correlation(
                            a,
                            b,
                            "username_similarity",
                            uname_result["confidence"],
                            evidence={
                                "levenshtein_score": uname_result["levenshtein_score"],
                                "phonetic_match": uname_result["phonetic_match"],
                            },
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

    def to_json(self) -> Dict[str, Any]:
        return self.backend.to_json(self.case_id)

    def get_networkx_graph(self):
        return self.backend.get_networkx_graph(self.case_id)