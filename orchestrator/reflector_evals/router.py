from __future__ import annotations

from fastapi import APIRouter

from orchestrator.db.db_manager import get_connection
from orchestrator.reflector_evals.schemas import EvalCompareRequest
from orchestrator.reflector_evals.runner import run_strategy_compare, list_evals, get_eval

router = APIRouter(prefix="/reflector/evals", tags=["reflector-evals"])


@router.post("/compare")
def compare(req: EvalCompareRequest):
    with get_connection() as conn:
        return run_strategy_compare(conn, req)


@router.get("/recent")
def recent(limit: int = 20):
    with get_connection() as conn:
        return list_evals(conn, limit=limit)


@router.get("/{eval_id}")
def get_one(eval_id: str):
    with get_connection() as conn:
        data = get_eval(conn, eval_id)
        return data or {"error": "not_found", "eval_id": eval_id}
