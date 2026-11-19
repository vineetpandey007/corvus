"""
Case Report Generator — turns a case's identity graph + ingested posts
into a structured, bullet-point report an analyst can read at a glance or
hand off to someone else.

This is deliberately rule-based/templated, not LLM-generated: every line
is derived directly and traceably from the graph's own data (confidence
scores, correlation types, alias lists), so there's nothing in the report
that isn't already backed by a specific correlation the pipeline found.
That traceability matters more here than natural-sounding prose — see
docs/ETHICS_AND_LEGAL.md's point about presenting every match as a lead,
never a conclusion.
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Dict, List


def build_case_report(
    case_title: str,
    legal_basis: str,
    graph_data: Dict,
    posts_data: List[Dict],
) -> Dict:
    """
    Build a structured report dict from a case's graph JSON
    ({"nodes": [...], "edges": [...]}, as returned by
    IdentityGraphBuilder.to_json()) and its ingested posts.
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    alias_names = [n["id"] for n in nodes]
    linked_aliases = set()
    for e in edges:
        linked_aliases.add(e["source"])
        linked_aliases.add(e["target"])
    isolated_aliases = [a for a in alias_names if a not in linked_aliases]

    # Highest-confidence findings first — an analyst skimming the report
    # should see the strongest leads before the weaker ones.
    findings = []
    for e in sorted(edges, key=lambda x: -x.get("confidence", 0)):
        types = ", ".join(t.replace("_", " ") for t in e.get("types", []))
        confidence_pct = round(e.get("confidence", 0) * 100)
        findings.append({
            "alias_a": e["source"],
            "alias_b": e["target"],
            "types": e.get("types", []),
            "confidence_pct": confidence_pct,
            "text": (
                f"\"{e['source']}\" and \"{e['target']}\" are likely linked via "
                f"{types} (confidence: {confidence_pct}%)"
            ),
        })

    source_counts = Counter((p.get("source") or "unknown") for p in posts_data)

    return {
        "case_title": case_title,
        "legal_basis": legal_basis or "(none recorded)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_aliases": len(alias_names),
            "total_posts": len(posts_data),
            "total_correlations": len(edges),
            "isolated_alias_count": len(isolated_aliases),
            "sources": dict(source_counts),
        },
        "findings": findings,
        "isolated_aliases": isolated_aliases,
    }


def report_to_bullet_text(report: Dict) -> str:
    """Render the report dict as plain bullet-point text (used for the
    TXT export and as the PDF's content source)."""
    lines = []
    lines.append(f"CASE REPORT: {report['case_title']}")
    lines.append(f"Legal basis: {report['legal_basis']}")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")
    lines.append("SUMMARY")
    s = report["summary"]
    lines.append(f"- {s['total_aliases']} aliases analyzed across {s['total_posts']} posts")
    lines.append(f"- {s['total_correlations']} correlation(s) found")
    lines.append(f"- {s['isolated_alias_count']} alias(es) show no correlation to any other")
    if s["sources"]:
        src_list = ", ".join(f"{k} ({v})" for k, v in s["sources"].items())
        lines.append(f"- Sources: {src_list}")
    lines.append("")
    lines.append("KEY FINDINGS")
    if report["findings"]:
        for f in report["findings"]:
            lines.append(f"- {f['text']}")
    else:
        lines.append("- No correlations were found among the ingested aliases.")
    if report["isolated_aliases"]:
        lines.append("")
        lines.append("UNCORRELATED ALIASES")
        for a in report["isolated_aliases"]:
            lines.append(f"- {a}: no correlation found with any other alias in this case")
    lines.append("")
    lines.append(
        "Note: every finding above is a probabilistic correlation, not a "
        "confirmed identity match. Treat each as a lead requiring further "
        "investigation, per docs/ETHICS_AND_LEGAL.md."
    )
    return "\n".join(lines)


def report_to_pdf(report: Dict, output_path: str) -> str:
    """Render the report as a PDF file at output_path. Returns the path."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem,
    )

    doc = SimpleDocTemplate(output_path, pagesize=letter, title=report["case_title"])
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(report["case_title"], styles["Title"]))
    story.append(Paragraph(f"Legal basis: {report['legal_basis']}", styles["Normal"]))
    story.append(Paragraph(f"Generated: {report['generated_at']}", styles["Normal"]))
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Summary", styles["Heading2"]))
    s = report["summary"]
    story.append(Paragraph(
        f"{s['total_aliases']} aliases analyzed across {s['total_posts']} posts &mdash; "
        f"{s['total_correlations']} correlation(s) found, "
        f"{s['isolated_alias_count']} alias(es) uncorrelated.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Key Findings", styles["Heading2"]))
    if report["findings"]:
        items = [ListItem(Paragraph(f["text"], styles["Normal"])) for f in report["findings"]]
        story.append(ListFlowable(items, bulletType="bullet"))
    else:
        story.append(Paragraph("No correlations were found.", styles["Normal"]))

    if report["isolated_aliases"]:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("Uncorrelated Aliases", styles["Heading2"]))
        items = [ListItem(Paragraph(a, styles["Normal"])) for a in report["isolated_aliases"]]
        story.append(ListFlowable(items, bulletType="bullet"))

    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        "<i>Every finding above is a probabilistic correlation, not a "
        "confirmed identity match. Treat each as a lead requiring further "
        "investigation.</i>",
        styles["Normal"],
    ))

    doc.build(story)
    return output_path
