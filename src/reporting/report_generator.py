"""
Case Report Generator — deterministic, rule-based forensic reporting with
underlying correlation evidence and SHA-256 chain-of-custody digests.
"""

import html
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List


def format_edge_evidence(edge: Dict[str, Any]) -> str:
    """Render structured edge `evidence` into a concise, traceable string."""
    ev = edge.get("evidence") or {}
    parts: List[str] = []

    wallet_ev = ev.get("wallet_reuse") or {}
    if wallet_ev.get("shared_addresses"):
        chains = f" [{', '.join(wallet_ev['chains'])}]" if wallet_ev.get("chains") else ""
        parts.append(f"shared wallet(s): {', '.join(wallet_ev['shared_addresses'])}{chains}")

    pgp_ev = ev.get("pgp_key_reuse") or {}
    if pgp_ev.get("shared_fingerprints"):
        parts.append(f"shared PGP fingerprint(s): {', '.join(pgp_ev['shared_fingerprints'])}")
    elif pgp_ev.get("shared_user_ids"):
        parts.append(f"shared PGP UID(s): {', '.join(pgp_ev['shared_user_ids'])}")

    stylo_ev = ev.get("stylometry") or {}
    breakdown = stylo_ev.get("breakdown") or {}
    if breakdown:
        parts.append(
            "stylometry breakdown "
            f"(char-ngram: {round(breakdown.get('char_ngram_similarity', 0) * 100)}%, "
            f"function-words: {round(breakdown.get('function_word_similarity', 0) * 100)}%, "
            f"POS: {round(breakdown.get('pos_similarity', 0) * 100)}%)"
        )

    uname_ev = ev.get("username_similarity") or {}
    if uname_ev:
        phonetic_note = ", phonetic match" if uname_ev.get("phonetic_match") else ""
        parts.append(
            f"handle similarity: {round(uname_ev.get('levenshtein_score', 0) * 100)}%{phonetic_note}"
        )

    return "; ".join(parts)


def build_case_report(
    case_title: str,
    legal_basis: str,
    graph_data: Dict[str, Any],
    posts_data: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build a structured forensic report dict from a case's graph JSON and
    decrypted posts (preserving all existing keys for backward compatibility).
    """
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    alias_names = [n["id"] for n in nodes]
    linked_aliases = set()
    for e in edges:
        linked_aliases.add(e["source"])
        linked_aliases.add(e["target"])
    isolated_aliases = [a for a in alias_names if a not in linked_aliases]

    findings = []
    for e in sorted(edges, key=lambda x: -x.get("confidence", 0)):
        types = ", ".join(t.replace("_", " ") for t in e.get("types", []))
        confidence_pct = round(e.get("confidence", 0) * 100)
        evidence_summary = format_edge_evidence(e)
        base_text = (
            f"\"{e['source']}\" and \"{e['target']}\" are likely linked via "
            f"{types} (confidence: {confidence_pct}%)"
        )
        full_text = f"{base_text} — {evidence_summary}" if evidence_summary else base_text

        findings.append({
            "alias_a": e["source"],
            "alias_b": e["target"],
            "types": e.get("types", []),
            "signal_scores": e.get("signal_scores", {}),
            "confidence_pct": confidence_pct,
            "evidence": e.get("evidence", {}),
            "evidence_summary": evidence_summary,
            "text": full_text,
        })

    source_counts = Counter((p.get("source") or "unknown") for p in posts_data)

    evidence_manifest = [
        {
            "alias": p.get("alias", "unknown"),
            "source": p.get("source") or "unknown",
            "evidence_sha256": p.get("evidence_sha256"),
        }
        for p in posts_data
        if p.get("evidence_sha256")
    ]

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
        "evidence_manifest": evidence_manifest,
    }


def report_to_bullet_text(report: Dict[str, Any]) -> str:
    """Render the report dict as plain bullet-point text for TXT export."""
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

    manifest = report.get("evidence_manifest") or []
    if manifest:
        lines.append("")
        lines.append("EVIDENCE CHAIN-OF-CUSTODY (SHA-256)")
        for idx, item in enumerate(manifest, start=1):
            lines.append(
                f"- Item #{idx} [{item['alias']} @ {item['source']}]: sha256:{item['evidence_sha256']}"
            )

    lines.append("")
    lines.append(
        "Note: every finding above is a probabilistic correlation, not a "
        "confirmed identity match. Treat each as a lead requiring further "
        "investigation, per docs/ETHICS_AND_LEGAL.md."
    )
    return "\n".join(lines)


def report_to_pdf(report: Dict[str, Any], output_path: str) -> str:
    """Render the report as an XML-safe PDF file at output_path."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        ListFlowable,
        ListItem,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    esc = html.escape
    doc = SimpleDocTemplate(output_path, pagesize=letter, title=report["case_title"])
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(esc(report["case_title"]), styles["Title"]))
    story.append(Paragraph(f"Legal basis: {esc(report['legal_basis'])}", styles["Normal"]))
    story.append(Paragraph(f"Generated: {esc(report['generated_at'])}", styles["Normal"]))
    story.append(Spacer(1, 0.25 * inch))

    story.append(Paragraph("Summary", styles["Heading2"]))
    s = report["summary"]
    story.append(
        Paragraph(
            f"{s['total_aliases']} aliases analyzed across {s['total_posts']} posts &mdash; "
            f"{s['total_correlations']} correlation(s) found, "
            f"{s['isolated_alias_count']} alias(es) uncorrelated.",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Key Findings", styles["Heading2"]))
    if report["findings"]:
        items = [ListItem(Paragraph(esc(f["text"]), styles["Normal"])) for f in report["findings"]]
        story.append(ListFlowable(items, bulletType="bullet"))
    else:
        story.append(Paragraph("No correlations were found.", styles["Normal"]))

    if report["isolated_aliases"]:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("Uncorrelated Aliases", styles["Heading2"]))
        items = [ListItem(Paragraph(esc(a), styles["Normal"])) for a in report["isolated_aliases"]]
        story.append(ListFlowable(items, bulletType="bullet"))

    manifest = report.get("evidence_manifest") or []
    if manifest:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("Evidence Chain-of-Custody (SHA-256)", styles["Heading2"]))
        items = [
            ListItem(
                Paragraph(
                    esc(
                        f"Item #{idx} [{item['alias']} @ {item['source']}]: "
                        f"sha256:{item['evidence_sha256']}"
                    ),
                    styles["Normal"],
                )
            )
            for idx, item in enumerate(manifest, start=1)
        ]
        story.append(ListFlowable(items, bulletType="bullet"))

    story.append(Spacer(1, 0.3 * inch))
    story.append(
        Paragraph(
            "<i>Every finding above is a probabilistic correlation, not a "
            "confirmed identity match. Treat each as a lead requiring further "
            "investigation.</i>",
            styles["Normal"],
        )
    )

    doc.build(story)
    return output_path