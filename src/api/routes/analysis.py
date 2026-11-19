"""
Standalone analysis routes — run a single correlation check (stylometry,
PGP, wallet trace) without needing a full case workflow. Useful for quick
lookups during triage, before an analyst commits to opening a case.

All routes require authentication. For persisted, case-scoped
investigations (with encrypted storage + audit trail), use the /cases
routes in src/api/routes/cases.py instead.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.stylometry.author_matcher import compare_authors
from src.identity_graph.pgp_correlator import correlate as pgp_correlate
from src.identity_graph.username_matcher import compare_usernames
from src.blockchain.wallet_tracer import trace_wallet
from src.identity_graph.graph_builder import IdentityGraphBuilder
from src.api.auth import get_current_user
from src.db.models import User

router = APIRouter(tags=["analysis"], dependencies=[Depends(get_current_user)])


class TextCompareRequest(BaseModel):
    alias_a: str
    text_a: str
    alias_b: str
    text_b: str


class UsernameCompareRequest(BaseModel):
    alias_a: str
    alias_b: str


class WalletTraceRequest(BaseModel):
    address: str
    chain: str = "ethereum"


@router.post("/analyze/text")
def analyze_text(req: TextCompareRequest):
    result = compare_authors(req.text_a, req.text_b)
    return {"alias_a": req.alias_a, "alias_b": req.alias_b, **result}


@router.post("/correlate/pgp")
def correlate_pgp(req: TextCompareRequest):
    result = pgp_correlate(req.text_a, req.text_b)
    return {"alias_a": req.alias_a, "alias_b": req.alias_b, **result}


@router.post("/correlate/username")
def correlate_username(req: UsernameCompareRequest):
    result = compare_usernames(req.alias_a, req.alias_b)
    return {"alias_a": req.alias_a, "alias_b": req.alias_b, **result}


@router.post("/trace/wallet")
def trace_wallet_route(req: WalletTraceRequest, user: User = Depends(get_current_user)):
    # Returns 200 even on a failed trace (see wallet_tracer.trace_wallet) —
    # a flaky third-party block-explorer API is an expected, recoverable
    # condition, flagged via result["error"], not a 5xx server fault.
    return trace_wallet(req.address, req.chain, actor=user.username)


@router.get("/graph/{case_id}")
def get_graph(case_id: str):
    """
    Quick-lookup graph retrieval scoped only by case_id string, sharing the
    same in-process graph backend as /cases/{case_id}/graph. For access-
    controlled, DB-backed case data ownership, prefer the /cases routes.
    """
    builder = IdentityGraphBuilder(case_id=case_id)
    return {"case_id": case_id, **builder.to_json()}
