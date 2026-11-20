"""
Rule-based natural-language query engine for case data.

Deterministic, zero-hallucination intent matching over graph edges,
forensic evidence artifacts, and SHA-256 chain-of-custody digests.
"""

import re
from typing import Any, Dict, List, Optional

from src.reporting.report_generator import format_edge_evidence

_TYPE_KEYWORDS = {
    "stylometry": ["stylometry", "writing style", "writing-style", "style"],
    "pgp_key_reuse": ["pgp", "key reuse", "key fingerprint", "public key"],
    "wallet_reuse": ["wallet", "crypto", "bitcoin", "ethereum", "address"],
    "username_similarity": ["username", "handle", "alias name", "name similarity"],
}


def _normalize(text: str) -> str:
    return text.strip().lower()


def _find_mentioned_alias(query_lower: str, alias_names: List[str]) -> Optional[str]:
    """
    Match a known alias using boundary-aware lookup (longest first) so short
    handles like 'is' or 'no' never collide inside ordinary English words.
    """
    sorted_aliases = sorted(alias_names, key=len, reverse=True)

    # 1. Explicit quoted mention wins immediately
    for alias in sorted_aliases:
        al = alias.lower()
        if f'"{al}"' in query_lower or f"'{al}'" in query_lower:
            return alias

    # 2. Boundary-aware token match (allows underscores/hyphens/dots inside handles)
    for alias in sorted_aliases:
        pattern = rf"(?<![a-z0-9_.-]){re.escape(alias.lower())}(?![a-z0-9_.-])"
        if re.search(pattern, query_lower):
            return alias

    return None


def _find_mentioned_type(query_lower: str) -> Optional[str]:
    for corr_type, keywords in _TYPE_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            return corr_type
    return None


def answer_query(
    query: str,
    graph_data: Dict[str, Any],
    posts_data: List[Dict[str, Any]],
    report: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Main entry point. Returns:
        {
            "answer": str,
            "matched_intent": str,
            "follow_up_questions": [str, ...],
        }
    """
    q = _normalize(query)
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    alias_names = [n["id"] for n in nodes]

    mentioned_alias = _find_mentioned_alias(q, alias_names)
    mentioned_type = _find_mentioned_type(q)

    # --- Intent: connections of a specific named alias ---
    if mentioned_alias and any(
        w in q for w in ["linked", "connect", "related", "correlat", "who is", "about"]
    ):
        return _answer_alias_connections(mentioned_alias, edges)

    # --- Intent: filter findings by correlation type ---
    if mentioned_type and any(w in q for w in ["find", "show", "which", "what", "list", "any"]):
        return _answer_findings_by_type(mentioned_type, report)

    # --- Intent: chain-of-custody / SHA-256 evidence digests ---
    if any(w in q for w in ["sha256", "sha-256", "hash", "digest", "custody", "manifest"]):
        return _answer_evidence_manifest(posts_data, report)

    # --- Intent: strongest / highest-confidence link ---
    if any(
        w in q for w in ["strongest", "highest confidence", "best match", "most confident", "top finding"]
    ):
        return _answer_strongest_link(report)

    # --- Intent: weakest link ---
    if any(w in q for w in ["weakest", "lowest confidence", "least confident"]):
        return _answer_weakest_link(report)

    # --- Intent: uncorrelated / isolated aliases ---
    if any(w in q for w in ["uncorrelated", "isolated", "not linked", "no correlation", "unlinked"]):
        return _answer_isolated_aliases(report)

    # --- Intent: counts / summary ---
    if any(w in q for w in ["how many", "count", "summar", "overview", "total"]):
        return _answer_summary(report)

    # --- Fallback ---
    return _answer_fallback(alias_names)


def _answer_alias_connections(alias: str, edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    connections = [e for e in edges if e["source"] == alias or e["target"] == alias]
    if not connections:
        answer = f'"{alias}" has no correlations with any other alias in this case.'
    else:
        parts = []
        for e in sorted(connections, key=lambda x: -x.get("confidence", 0)):
            other = e["target"] if e["source"] == alias else e["source"]
            types = ", ".join(t.replace("_", " ") for t in e.get("types", []))
            ev_str = format_edge_evidence(e)
            detail = f" [{ev_str}]" if ev_str else ""
            parts.append(f'"{other}" via {types} ({round(e.get("confidence", 0) * 100)}%){detail}')
        answer = f'"{alias}" is linked to: ' + "; ".join(parts) + "."

    follow_ups = [f'What is the strongest link for "{alias}"?'] if connections else []
    follow_ups += ["Show me uncorrelated aliases", "Summarize this case"]
    return {
        "answer": answer,
        "matched_intent": "alias_connections",
        "follow_up_questions": follow_ups[:3],
    }


def _answer_findings_by_type(corr_type: str, report: Dict[str, Any]) -> Dict[str, Any]:
    matches = [f for f in report["findings"] if corr_type in f.get("types", [])]
    label = corr_type.replace("_", " ")
    if not matches:
        answer = f"No {label} correlations were found in this case."
    else:
        lines = [f["text"] for f in matches]
        answer = f"{len(matches)} {label} correlation(s) found:\n- " + "\n- ".join(lines)
    return {
        "answer": answer,
        "matched_intent": f"findings_by_type:{corr_type}",
        "follow_up_questions": [
            "What is the strongest finding overall?",
            "Show me uncorrelated aliases",
            "Summarize this case",
        ],
    }


def _answer_evidence_manifest(
    posts_data: List[Dict[str, Any]], report: Dict[str, Any]
) -> Dict[str, Any]:
    manifest = report.get("evidence_manifest") or [
        {
            "alias": p.get("alias", "unknown"),
            "source": p.get("source") or "unknown",
            "evidence_sha256": p.get("evidence_sha256"),
        }
        for p in posts_data
        if p.get("evidence_sha256")
    ]
    if not manifest:
        answer = "No SHA-256 evidence digests are recorded for this case yet."
    else:
        lines = [
            f"[{m['alias']} @ {m['source']}] sha256:{m['evidence_sha256']}"
            for m in manifest
        ]
        answer = f"{len(manifest)} evidence item(s) hashed at ingestion:\n- " + "\n- ".join(lines)

    return {
        "answer": answer,
        "matched_intent": "evidence_manifest",
        "follow_up_questions": ["Summarize this case", "What is the strongest finding?"],
    }


def _answer_strongest_link(report: Dict[str, Any]) -> Dict[str, Any]:
    if not report["findings"]:
        return {
            "answer": "There are no correlations in this case yet.",
            "matched_intent": "strongest_link",
            "follow_up_questions": ["Summarize this case"],
        }
    top = report["findings"][0]
    answer = f"The strongest finding is: {top['text']}"
    return {
        "answer": answer,
        "matched_intent": "strongest_link",
        "follow_up_questions": [
            f"What else is \"{top['alias_a']}\" linked to?",
            "What is the weakest finding?",
            "Summarize this case",
        ],
    }


def _answer_weakest_link(report: Dict[str, Any]) -> Dict[str, Any]:
    if not report["findings"]:
        return {
            "answer": "There are no correlations in this case yet.",
            "matched_intent": "weakest_link",
            "follow_up_questions": ["Summarize this case"],
        }
    bottom = report["findings"][-1]
    answer = f"The weakest finding is: {bottom['text']}"
    return {
        "answer": answer,
        "matched_intent": "weakest_link",
        "follow_up_questions": ["What is the strongest finding?", "Summarize this case"],
    }


def _answer_isolated_aliases(report: Dict[str, Any]) -> Dict[str, Any]:
    isolated = report["isolated_aliases"]
    if not isolated:
        answer = "Every alias in this case has at least one correlation."
    else:
        answer = f"{len(isolated)} alias(es) have no correlation: " + ", ".join(isolated)
    return {
        "answer": answer,
        "matched_intent": "isolated_aliases",
        "follow_up_questions": ["Summarize this case", "What is the strongest finding?"],
    }


def _answer_summary(report: Dict[str, Any]) -> Dict[str, Any]:
    s = report["summary"]
    answer = (
        f"{s['total_aliases']} aliases analyzed across {s['total_posts']} posts — "
        f"{s['total_correlations']} correlation(s) found, {s['isolated_alias_count']} uncorrelated."
    )
    return {
        "answer": answer,
        "matched_intent": "summary",
        "follow_up_questions": [
            "What is the strongest finding?",
            "Show me uncorrelated aliases",
            "Show evidence hashes",
        ],
    }


def _answer_fallback(alias_names: List[str]) -> Dict[str, Any]:
    example_alias = alias_names[0] if alias_names else "<alias>"
    answer = (
        "I didn't understand that — this works from the case's own data with "
        "built-in question patterns, not an open-ended AI chat. Try asking things like:\n"
        "- \"Summarize this case\"\n"
        "- \"What is the strongest finding?\"\n"
        f"- \"Who is {example_alias} linked to?\"\n"
        "- \"Show me uncorrelated aliases\"\n"
        "- \"Find PGP key reuse\" / \"Find wallet reuse\" / \"Find username similarity\"\n"
        "- \"Show evidence hashes\""
    )
    return {
        "answer": answer,
        "matched_intent": "fallback",
        "follow_up_questions": ["Summarize this case", "What is the strongest finding?"],
    }