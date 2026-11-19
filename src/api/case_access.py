"""
Shared case-ownership lookup — used by routes/cases.py, routes/reports.py,
and routes/nlp.py so "does this case exist AND belong to this analyst"
is checked exactly one way everywhere, rather than three slightly-
different inline queries drifting apart over time.
"""

from typing import Dict, List, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.db.models import Case, CasePost, User
from src.identity_graph.graph_builder import IdentityGraphBuilder
from src.utils.encryption import decrypt_text


def get_owned_case(case_id: str, db: Session, user: User) -> Case:
    case = db.query(Case).filter(Case.case_id == case_id, Case.owner_id == user.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


def get_case_data(case: Case, db: Session) -> Tuple[Dict, List[Dict]]:
    """
    Returns (graph_data, posts_data) for a case — the two inputs every
    downstream feature (report generation, NLP queries, suggestions)
    builds on. Decrypts post text once here rather than each caller
    re-querying and re-decrypting separately.
    """
    posts = db.query(CasePost).filter(CasePost.case_id == case.id).all()
    posts_data = [
        {"alias": p.alias, "source": p.source, "text": decrypt_text(p.text_encrypted)}
        for p in posts
    ]
    graph_data = IdentityGraphBuilder(case_id=case.case_id).to_json()
    return graph_data, posts_data
