from src.reporting.report_generator import build_case_report, report_to_bullet_text


SAMPLE_GRAPH = {
    "nodes": [
        {"id": "alias_a", "type": "alias"},
        {"id": "alias_b", "type": "alias"},
        {"id": "alias_c", "type": "alias"},
    ],
    "edges": [
        {"source": "alias_a", "target": "alias_b", "types": ["stylometry"], "confidence": 0.91},
    ],
}

SAMPLE_POSTS = [
    {"alias": "alias_a", "source": "forum_x", "text": "..."},
    {"alias": "alias_b", "source": "forum_y", "text": "..."},
    {"alias": "alias_c", "source": "forum_x", "text": "..."},
]


def test_build_case_report_identifies_isolated_alias():
    report = build_case_report("Test Case", "warrant-001", SAMPLE_GRAPH, SAMPLE_POSTS)
    assert report["summary"]["total_aliases"] == 3
    assert report["summary"]["total_correlations"] == 1
    assert report["isolated_aliases"] == ["alias_c"]


def test_build_case_report_finding_text_includes_confidence():
    report = build_case_report("Test Case", "warrant-001", SAMPLE_GRAPH, SAMPLE_POSTS)
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert finding["confidence_pct"] == 91
    assert "alias_a" in finding["text"] and "alias_b" in finding["text"]
    assert "stylometry" in finding["text"]


def test_build_case_report_counts_sources():
    report = build_case_report("Test Case", "warrant-001", SAMPLE_GRAPH, SAMPLE_POSTS)
    assert report["summary"]["sources"] == {"forum_x": 2, "forum_y": 1}


def test_build_case_report_handles_no_correlations():
    empty_graph = {"nodes": [{"id": "solo_alias", "type": "alias"}], "edges": []}
    report = build_case_report("Empty Case", "", empty_graph, [])
    assert report["findings"] == []
    assert report["isolated_aliases"] == ["solo_alias"]
    assert report["legal_basis"] == "(none recorded)"


def test_report_to_bullet_text_contains_key_sections():
    report = build_case_report("Test Case", "warrant-001", SAMPLE_GRAPH, SAMPLE_POSTS)
    text = report_to_bullet_text(report)
    assert "CASE REPORT: Test Case" in text
    assert "KEY FINDINGS" in text
    assert "UNCORRELATED ALIASES" in text
    assert "alias_c" in text
    assert "probabilistic correlation" in text
