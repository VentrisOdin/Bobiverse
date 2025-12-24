from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EvalCompareRequest(BaseModel):
    target_module: Optional[str] = Field(default=None)
    target_node: Optional[str] = Field(default=None)

    # Use "NULL" (string) to refer to legacy rows where strategy_name IS NULL
    baseline_strategy: str
    candidate_strategy: str

    limit_per_strategy: int = Field(default=200, ge=10, le=5000)
    days_back: Optional[int] = Field(default=30, ge=1, le=365)


class StrategyMetrics(BaseModel):
    strategy_name: str
    total: int
    success: int
    failed: int
    success_rate: float
    failed_rate: float
    avg_latency_ms: Optional[float] = None
    top_error_types: List[Dict[str, Any]] = Field(default_factory=list)


class EvalCompareReport(BaseModel):
    eval_id: str
    created_at: str
    scope: Dict[str, Any]
    baseline: StrategyMetrics
    candidate: StrategyMetrics
    delta: Dict[str, Any]
    verdict: str  # "promote" | "reject" | "review"
