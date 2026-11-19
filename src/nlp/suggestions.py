"""
Investigative next-step suggestions — rule-based heuristics over a case's
current graph/post state, surfaced as plain-language recommendations.

Like query_engine.py, deliberately not LLM-generated: each suggestion is
triggered by a specific, inspectable condition (see the rules in
generate_suggestions), so "why did it suggest this" always has a concrete
answer traceable to the case data, not a model's free-form reasoning.
"""

from collections import Counter
from typing import Dict, List


def generate_suggestions(graph_data: Dict, posts_data: List[Dict], report: Dict) -> List[Dict]:
    """
    Returns a list of {"suggestion": str, "reason": str} dicts, most
    actionable first. Each rule is independent — several can fire at once.
    """
    suggestions = []
    edges = graph_data.get("edges", [])
    nodes = graph_data.get("nodes", [])
    isolated = report["isolated_aliases"]
    findings = report["findings"]

    # Rule 1: too little data to say much yet
    if len(posts_data) < 3:
        suggestions.append({
            "suggestion": "Ingest more posts for this case before drawing conclusions.",
            "reason": f"Only {len(posts_data)} post(s) ingested so far — stylometry and "
                      f"pattern-based signals need more text per alias to be reliable.",
        })

    # Rule 2: isolated aliases worth chasing further
    if isolated:
        suggestions.append({
            "suggestion": f"Look for more posts from {', '.join(isolated[:3])}"
                           f"{'...' if len(isolated) > 3 else ''} on other forums/sources.",
            "reason": "These aliases show no correlation yet — that can mean they're "
                      "genuinely unrelated, or just that too little text has been "
                      "ingested for them specifically.",
        })

    # Rule 3: single-signal-only pairs — weak corroboration
    type_counts_per_pair = Counter()
    for e in edges:
        pair = tuple(sorted([e["source"], e["target"]]))
        type_counts_per_pair[pair] = len(e.get("types", []))
    single_signal_pairs = [pair for pair, count in type_counts_per_pair.items() if count == 1]
    if single_signal_pairs:
        a, b = single_signal_pairs[0]
        suggestions.append({
            "suggestion": f'Look for a second, independent signal linking "{a}" and "{b}" '
                          f"(e.g. a shared PGP key or wallet) before treating this as a strong lead.",
            "reason": "This pair is currently linked by only one correlation type — "
                      "corroborating with an independent signal meaningfully raises confidence.",
        })

    # Rule 4: a very high-confidence finding worth prioritizing
    high_conf = [f for f in findings if f["confidence_pct"] >= 95]
    if high_conf:
        top = high_conf[0]
        suggestions.append({
            "suggestion": f'Prioritize following up on "{top["alias_a"]}" / "{top["alias_b"]}" '
                          f"— this is your highest-confidence lead.",
            "reason": f"{top['confidence_pct']}% confidence via {', '.join(t.replace('_', ' ') for t in top['types'])}.",
        })

    # Rule 5: only username-similarity signals present anywhere — flag the weak-evidence pattern
    only_username = edges and all(
        set(e.get("types", [])) <= {"username_similarity"} for e in edges
    )
    if only_username:
        suggestions.append({
            "suggestion": "Treat the current links cautiously — they're based on handle "
                          "similarity alone, which is deliberately capped at low confidence.",
            "reason": "No stylometry, PGP, or wallet corroboration found yet for any pair.",
        })

    # Rule 6: no correlations found at all
    if not edges and len(posts_data) >= 3:
        suggestions.append({
            "suggestion": "No correlations found across the ingested posts — consider "
                          "whether these aliases are genuinely unrelated, or ingest posts "
                          "from a wider date range/source set.",
            "reason": f"{len(nodes)} aliases ingested, zero correlations detected.",
        })

    # Rule 7: healthy case — always offer the export reminder as a gentle default
    if findings:
        suggestions.append({
            "suggestion": "Export this case's report (PDF/TXT) for your case file once you're "
                          "satisfied with the current findings.",
            "reason": "Keeps a timestamped record of what the pipeline found and when.",
        })

    return suggestions
