"""
NLP query and investigative-suggestion routes — see src/nlp/query_engine.py
and src/nlp/suggestions.py for the (rule-based, not LLM-backed) logic
itself. Both routes build on the same report data the Report tab uses,
via src/api/case_access.py.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import User
from src.api.auth import get_current_user
from src.api.case_access import get_owned_case, get_case_data
from src.nlp.query_engine import answer_query
from src.nlp.suggestions import generate_suggestions
from src.reporting.report_generator import build_case_report
from src.utils.logger import audit_log

router = APIRouter(prefix="/cases", tags=["nlp"])


class QueryRequest(BaseModel):
    query: str


@router.post("/{case_id}/query")
def query_case(
    case_id: str,
    req: QueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    case = get_owned_case(case_id, db, user)
    graph_data, posts_data = get_case_data(case, db)
    report = build_case_report(case.title, case.legal_basis, graph_data, posts_data)

    result = answer_query(req.query, graph_data, posts_data, report)

    audit_log(
        action="nlp_query",
        actor=user.username,
        details={"case_id": case_id, "query": req.query, "matched_intent": result["matched_intent"]},
    )
    return result


@router.get("/{case_id}/suggestions")
def get_case_suggestions(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_owned_case(case_id, db, user)
    graph_data, posts_data = get_case_data(case, db)
    report = build_case_report(case.title, case.legal_basis, graph_data, posts_data)

    suggestions = generate_suggestions(graph_data, posts_data, report)
    return {"case_id": case_id, "suggestions": suggestions}
