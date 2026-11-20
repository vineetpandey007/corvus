"""
Shared case-ownership lookup and graph rehydration helper.
"""

from typing import Any, Dict, List, Tuple

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.db.models import Case, CasePost, User
from src.identity_graph.graph_builder import IdentityGraphBuilder
from src.utils.encryption import decrypt_text, hash_evidence


def get_owned_case(case_id: str, db: Session, user: User) -> Case:
    case = db.query(Case).filter(Case.case_id == case_id, Case.owner_id == user.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


def get_case_data(case: Case, db: Session) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Returns (graph_data, posts_data) for a case.
    Decrypts post text once and automatically rehydrates the in-memory graph
    from persisted posts if the backend restarted since ingestion.
    """
    posts = (
        db.query(CasePost)
        .filter(CasePost.case_id == case.id)
        .order_by(CasePost.id.asc())
        .all()
    )

    posts_data: List[Dict[str, Any]] = []
    for p in posts:
        plaintext = decrypt_text(p.text_encrypted)
        posts_data.append({
            "id": p.id,
            "alias": p.alias,
            "source": p.source,
            "text": plaintext,
            "evidence_sha256": p.evidence_sha256 or hash_evidence(plaintext),
        })

    builder = IdentityGraphBuilder(case_id=case.case_id)
    graph_data = builder.to_json()

    # Rehydrate in-memory graph if posts exist in DB but graph cache is cold (e.g. post-restart)
    if posts_data and not graph_data.get("nodes"):
        graph_data = builder.build_from_posts(posts_data, actor="system:rehydrate").to_json()

    return graph_data, posts_data