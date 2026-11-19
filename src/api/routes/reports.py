"""
Report routes — structured bullet-point case reports, plus TXT/PDF export.

PNG/JPG graph image export is handled client-side (Cytoscape.js's own
cy.png()/cy.jpg() export, triggered from the frontend's GraphView) rather
than here, since the graph the analyst is looking at (their current pan/
zoom/layout) is the more useful export than a freshly server-rendered
one — see frontend/src/components/GraphView.jsx.
"""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import Case, User
from src.api.auth import get_current_user
from src.api.case_access import get_owned_case, get_case_data
from src.reporting.report_generator import build_case_report, report_to_bullet_text, report_to_pdf
from src.utils.logger import audit_log

router = APIRouter(prefix="/cases", tags=["reports"])


def build_report_for_case(case: Case, db: Session) -> dict:
    graph_data, posts_data = get_case_data(case, db)
    return build_case_report(case.title, case.legal_basis, graph_data, posts_data)


@router.get("/{case_id}/report")
def get_case_report(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Structured JSON report — summary stats + a bullet-point findings list."""
    case = get_owned_case(case_id, db, user)
    return build_report_for_case(case, db)


@router.get("/{case_id}/export/txt")
def export_case_txt(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_owned_case(case_id, db, user)
    report = build_report_for_case(case, db)
    text = report_to_bullet_text(report)

    audit_log(action="export_report", actor=user.username, details={"case_id": case_id, "format": "txt"})

    return PlainTextResponse(
        text,
        headers={"Content-Disposition": f'attachment; filename="case_{case_id}_report.txt"'},
    )


@router.get("/{case_id}/export/pdf")
def export_case_pdf(case_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    case = get_owned_case(case_id, db, user)
    report = build_report_for_case(case, db)

    tmp_dir = Path(tempfile.gettempdir())
    output_path = tmp_dir / f"case_{case_id}_report.pdf"
    report_to_pdf(report, str(output_path))

    audit_log(action="export_report", actor=user.username, details={"case_id": case_id, "format": "pdf"})

    return FileResponse(
        str(output_path),
        media_type="application/pdf",
        filename=f"case_{case_id}_report.pdf",
    )
