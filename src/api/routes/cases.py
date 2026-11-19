"""
Case management routes — this is the real, end-to-end workflow:

1. POST /cases            — analyst opens a new case (with a legal-basis note)
2. POST /cases/{id}/ingest — analyst submits posts; stored encrypted at rest
                              in the DB, and run through the correlation
                              pipeline (stylometry, PGP, wallet, username)
3. GET  /cases/{id}/graph  — retrieve the resulting identity graph
4. GET  /cases             — list the current analyst's cases

All routes require authentication (JWT or service API key) and every
ingest/graph-build action is written to the audit log for chain of custody.
"""

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import Case, CasePost, User
from src.api.auth import get_current_user
from src.identity_graph.graph_builder import IdentityGraphBuilder
from src.utils.encryption import encrypt_text, decrypt_text
from src.utils.logger import audit_log

router = APIRouter(prefix="/cases", tags=["cases"])


class CreateCaseRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    legal_basis: str = Field(
        default="", description="Warrant/court-order/authorization reference for this investigation"
    )


class CaseResponse(BaseModel):
    case_id: str
    title: str
    legal_basis: str

    model_config = ConfigDict(from_attributes=True)


class PostIn(BaseModel):
    alias: str
    text: str
    source: str = ""


class IngestRequest(BaseModel):
    posts: List[PostIn]


@router.post("", response_model=CaseResponse, status_code=status.HTTP_201_CREATED)
def create_case(req: CreateCaseRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = Case(
        case_id=str(uuid.uuid4())[:8],
        title=req.title,
        legal_basis=req.legal_basis,
        owner_id=user.id,
    )
    db.add(case)
    db.commit()
    db.refresh(case)

    audit_log(action="create_case", actor=user.username, details={"case_id": case.case_id, "title": case.title})
    return CaseResponse(case_id=case.case_id, title=case.title, legal_basis=case.legal_basis or "")


@router.get("", response_model=List[CaseResponse])
def list_cases(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    cases = db.query(Case).filter(Case.owner_id == user.id).all()
    return [CaseResponse(case_id=c.case_id, title=c.title, legal_basis=c.legal_basis or "") for c in cases]


@router.post("/{case_id}/ingest")
def ingest_posts(
    case_id: str,
    req: IngestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    case = db.query(Case).filter(Case.case_id == case_id, Case.owner_id == user.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Persist posts encrypted at rest
    for post in req.posts:
        db.add(CasePost(
            case_id=case.id,
            alias=post.alias,
            source=post.source,
            text_encrypted=encrypt_text(post.text),
        ))
    db.commit()

    # Run the correlation pipeline on the plaintext (in-memory only, never
    # written to disk unencrypted) and update the case's identity graph.
    posts_for_pipeline = [{"alias": p.alias, "text": p.text, "source": p.source} for p in req.posts]
    builder = IdentityGraphBuilder(case_id=case_id)
    builder.build_from_posts(posts_for_pipeline, actor=user.username)

    audit_log(
        action="ingest_case_posts",
        actor=user.username,
        details={"case_id": case_id, "count": len(req.posts)},
    )

    return {"case_id": case_id, "ingested": len(req.posts), "graph": builder.to_json()}


@router.get("/{case_id}/graph")
def get_case_graph(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = db.query(Case).filter(Case.case_id == case_id, Case.owner_id == user.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    builder = IdentityGraphBuilder(case_id=case_id)
    return {"case_id": case_id, **builder.to_json()}


@router.get("/{case_id}/posts")
def get_case_posts(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Decrypt and return this case's stored posts (analyst review view)."""
    case = db.query(Case).filter(Case.case_id == case_id, Case.owner_id == user.id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    posts = db.query(CasePost).filter(CasePost.case_id == case.id).all()
    return [
        {
            "alias": p.alias,
            "source": p.source,
            "text": decrypt_text(p.text_encrypted),
            "created_at": p.created_at.isoformat(),
        }
        for p in posts
    ]
