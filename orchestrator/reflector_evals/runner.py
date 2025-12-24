from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from orchestrator.reflector_evals.schemas import EvalCompareRequest, StrategyMetrics, EvalCompareReport


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_eval_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reflector_eval_runs (
            eval_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            eval_type TEXT NOT NULL,
            scope_json TEXT NOT NULL,
            baseline_strategy TEXT NOT NULL,
            candidate_strategy TEXT NOT NULL,
            report_json TEXT NOT NULL,
            verdict TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _strategy_where(strategy_name: str) -> Tuple[str, List[Any]]:
    # Special keyword to compare legacy NULL strategy rows
    if strategy_name.upper() == "NULL":
        return "te.strategy_name IS NULL", []
    return "te.strategy_name = ?", [strategy_name]


def _fetch_metrics(
    conn: sqlite3.Connection,
    strategy_name: str,
    target_module: Optional[str],
    target_node: Optional[str],
    limit: int,
    days_back: Optional[int],
) -> StrategyMetrics:
    where_clauses: List[str] = []
    params: List[Any] = []

    w, p = _strategy_where(strategy_name)
    where_clauses.append(w)
    params.extend(p)

    if target_module:
        where_clauses.append("te.target_module = ?")
        params.append(target_module)

    if target_node:
        where_clauses.append("te.target_node = ?")
        params.append(target_node)

    if days_back is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        where_clauses.append("datetime(te.started_at) >= datetime(?)")
        params.append(cutoff.isoformat())

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    rows = conn.execute(
        f"""
        SELECT te.status, te.latency_ms, te.error_type
        FROM task_executions te
        WHERE {where_sql}
        ORDER BY datetime(te.started_at) DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()

    total = len(rows)
    success = sum(1 for r in rows if (r[0] or "").lower() == "success")
    failed = sum(1 for r in rows if (r[0] or "").lower() == "failed")

    latencies = [r[1] for r in rows if r[1] is not None]
    avg_latency = (sum(latencies) / len(latencies)) if latencies else None

    err_counts: Dict[str, int] = {}
    for _, _, err in rows:
        if err is None:
            continue
        err_counts[str(err)] = err_counts.get(str(err), 0) + 1

    top_error_types = [
        {"error_type": k, "count": v}
        for k, v in sorted(err_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
    ]

    success_rate = (success / total) if total else 0.0
    failed_rate = (failed / total) if total else 0.0

    return StrategyMetrics(
        strategy_name=strategy_name,
        total=total,
        success=success,
        failed=failed,
        success_rate=round(success_rate, 4),
        failed_rate=round(failed_rate, 4),
        avg_latency_ms=round(avg_latency, 2) if avg_latency is not None else None,
        top_error_types=top_error_types,
    )


def _verdict(baseline: StrategyMetrics, candidate: StrategyMetrics) -> Tuple[str, Dict[str, Any]]:
    # Conservative decision rule for v1:
    # promote: +5% success_rate and not >5% slower (if latency exists)
    # reject : -3% success_rate
    # else   : review
    delta_success = candidate.success_rate - baseline.success_rate

    latency_ok = (
        baseline.avg_latency_ms is None
        or candidate.avg_latency_ms is None
        or candidate.avg_latency_ms <= baseline.avg_latency_ms * 1.05
    )

    if delta_success >= 0.05 and latency_ok:
        verdict = "promote"
    elif delta_success <= -0.03:
        verdict = "reject"
    else:
        verdict = "review"

    delta = {
        "delta_success_rate": round(delta_success, 4),
        "baseline_success_rate": baseline.success_rate,
        "candidate_success_rate": candidate.success_rate,
        "baseline_avg_latency_ms": baseline.avg_latency_ms,
        "candidate_avg_latency_ms": candidate.avg_latency_ms,
        "latency_ok": latency_ok,
        "baseline_total": baseline.total,
        "candidate_total": candidate.total,
    }
    return verdict, delta


def run_strategy_compare(conn: sqlite3.Connection, req: EvalCompareRequest) -> EvalCompareReport:
    ensure_eval_tables(conn)

    eval_id = str(uuid.uuid4())
    created_at = _utc_now_iso()

    baseline = _fetch_metrics(
        conn,
        strategy_name=req.baseline_strategy,
        target_module=req.target_module,
        target_node=req.target_node,
        limit=req.limit_per_strategy,
        days_back=req.days_back,
    )
    candidate = _fetch_metrics(
        conn,
        strategy_name=req.candidate_strategy,
        target_module=req.target_module,
        target_node=req.target_node,
        limit=req.limit_per_strategy,
        days_back=req.days_back,
    )

    verdict, delta = _verdict(baseline, candidate)

    report = EvalCompareReport(
        eval_id=eval_id,
        created_at=created_at,
        scope={
            "target_module": req.target_module,
            "target_node": req.target_node,
            "limit_per_strategy": req.limit_per_strategy,
            "days_back": req.days_back,
        },
        baseline=baseline,
        candidate=candidate,
        delta=delta,
        verdict=verdict,
    )

    conn.execute(
        """
        INSERT INTO reflector_eval_runs
            (eval_id, created_at, eval_type, scope_json, baseline_strategy, candidate_strategy, report_json, verdict)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            eval_id,
            created_at,
            "strategy_compare",
            json.dumps(report.scope),
            req.baseline_strategy,
            req.candidate_strategy,
            report.model_dump_json(),
            verdict,
        ),
    )
    conn.commit()

    return report


def list_evals(conn: sqlite3.Connection, limit: int = 20) -> List[Dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT eval_id, created_at, eval_type, baseline_strategy, candidate_strategy, verdict
        FROM reflector_eval_runs
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    return [
        {
            "eval_id": r[0],
            "created_at": r[1],
            "eval_type": r[2],
            "baseline_strategy": r[3],
            "candidate_strategy": r[4],
            "verdict": r[5],
        }
        for r in rows
    ]


def get_eval(conn: sqlite3.Connection, eval_id: str) -> Optional[Dict[str, Any]]:
    row = conn.execute(
        "SELECT report_json FROM reflector_eval_runs WHERE eval_id = ?",
        (eval_id,),
    ).fetchone()
    if not row:
        return None
    return json.loads(row[0])
