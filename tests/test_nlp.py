"""
Unit tests for the rule-based NLP query engine and suggestions module —
no server/DB needed, these operate on plain graph/report dicts directly.
"""

from src.nlp.query_engine import answer_query
from src.nlp.suggestions import generate_suggestions
from src.reporting.report_generator import build_case_report


GRAPH = {
    "nodes": [
        {"id": "shadowbroker99", "type": "alias"},
        {"id": "night_wolf_23", "type": "alias"},
        {"id": "lonely_alias", "type": "alias"},
    ],
    "edges": [
        {
            "source": "shadowbroker99", "target": "night_wolf_23",
            "types": ["stylometry", "pgp_key_reuse"], "confidence": 0.98,
        },
    ],
}
POSTS = [
    {"alias": "shadowbroker99", "source": "forum_a", "text": "..."},
    {"alias": "night_wolf_23", "source": "forum_b", "text": "..."},
    {"alias": "lonely_alias", "source": "forum_c", "text": "..."},
]
REPORT = build_case_report("Test Case", "warrant-1", GRAPH, POSTS)


def test_summary_query():
    result = answer_query("give me a summary", GRAPH, POSTS, REPORT)
    assert result["matched_intent"] == "summary"
    assert "3 aliases" in result["answer"]
    assert "1 correlation" in result["answer"]


def test_strongest_link_query():
    result = answer_query("what's the strongest finding?", GRAPH, POSTS, REPORT)
    assert result["matched_intent"] == "strongest_link"
    assert "shadowbroker99" in result["answer"] and "night_wolf_23" in result["answer"]


def test_alias_connections_query():
    result = answer_query("who is shadowbroker99 linked to?", GRAPH, POSTS, REPORT)
    assert result["matched_intent"] == "alias_connections"
    assert "night_wolf_23" in result["answer"]


def test_alias_connections_query_no_links():
    result = answer_query("who is lonely_alias linked to?", GRAPH, POSTS, REPORT)
    assert result["matched_intent"] == "alias_connections"
    assert "no correlations" in result["answer"]


def test_isolated_aliases_query():
    result = answer_query("show me uncorrelated aliases", GRAPH, POSTS, REPORT)
    assert result["matched_intent"] == "isolated_aliases"
    assert "lonely_alias" in result["answer"]


def test_findings_by_type_query_pgp():
    result = answer_query("find pgp key reuse", GRAPH, POSTS, REPORT)
    assert result["matched_intent"] == "findings_by_type:pgp_key_reuse"
    assert "1 pgp" in result["answer"].lower()


def test_findings_by_type_query_no_matches():
    result = answer_query("find wallet reuse", GRAPH, POSTS, REPORT)
    assert "No wallet reuse" in result["answer"]


def test_fallback_for_unrecognized_query():
    result = answer_query("asdkjashdkjashd random gibberish", GRAPH, POSTS, REPORT)
    assert result["matched_intent"] == "fallback"
    assert "didn't understand" in result["answer"]


def test_every_response_has_follow_up_questions():
    for q in ["summary", "strongest finding", "who is shadowbroker99 linked to", "gibberish xyz"]:
        result = answer_query(q, GRAPH, POSTS, REPORT)
        assert isinstance(result["follow_up_questions"], list)
        assert len(result["follow_up_questions"]) >= 1


def test_suggestions_flag_isolated_alias():
    suggestions = generate_suggestions(GRAPH, POSTS, REPORT)
    texts = " ".join(s["suggestion"] for s in suggestions)
    assert "lonely_alias" in texts


def test_suggestions_flag_high_confidence_lead():
    suggestions = generate_suggestions(GRAPH, POSTS, REPORT)
    texts = " ".join(s["suggestion"] for s in suggestions)
    assert "shadowbroker99" in texts and "prioritize" in texts.lower()


def test_suggestions_for_low_post_count():
    small_graph = {"nodes": [{"id": "a", "type": "alias"}], "edges": []}
    small_posts = [{"alias": "a", "source": "x", "text": "..."}]
    small_report = build_case_report("Small", "", small_graph, small_posts)
    suggestions = generate_suggestions(small_graph, small_posts, small_report)
    assert any("Ingest more posts" in s["suggestion"] for s in suggestions)


def test_suggestions_flag_username_only_weak_evidence():
    weak_graph = {
        "nodes": [{"id": "a", "type": "alias"}, {"id": "b", "type": "alias"}],
        "edges": [{"source": "a", "target": "b", "types": ["username_similarity"], "confidence": 0.5}],
    }
    weak_posts = [{"alias": "a", "source": "x", "text": "..." * 50}, {"alias": "b", "source": "y", "text": "..." * 50}]
    weak_report = build_case_report("Weak", "", weak_graph, weak_posts)
    suggestions = generate_suggestions(weak_graph, weak_posts, weak_report)
    assert any("handle similarity alone" in s["suggestion"] for s in suggestions)
