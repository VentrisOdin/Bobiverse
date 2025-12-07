# orchestrator/reflector_service.py

import json
import logging
from typing import List, Optional

from fastapi import FastAPI
from pydantic import BaseModel

from db.db_manager import get_connection  # reuse same DB connection helper

logger = logging.getLogger("reflector")
logger.setLevel(logging.INFO)


app = FastAPI(
    title="Bobiverse Reflector v1",
    description=(
        "Analytics and basic self-reflection over Bobiverse task history. "
        "Provides raw stats for the Reflector LLM to learn from."
    ),
    version="1.0.0",
)


# ---------- Core Models (v0, kept) ---------- #

class TaskSummary(BaseModel):
    total_tasks: int
    success_count: int
    failed_count: int
    success_rate: float


class NodeErrorStats(BaseModel):
    node_name: str
    total_executions: int
    failed_executions: int
    failed_rate: float


class ModuleErrorStats(BaseModel):
    module_name: str
    total_executions: int
    failed_executions: int
    failed_rate: float


class FailedTask(BaseModel):
    task_uuid: str
    high_level_type: Optional[str] = None
    final_status: Optional[str] = None
    error_type: Optional[str] = None
    created_at: str  # ISO string from DB


# ---------- New v1 Models ---------- #

class ExecutionOverview(BaseModel):
    execution_id: int
    task_uuid: str
    high_level_type: Optional[str] = None
    target_module: Optional[str] = None
    target_node: Optional[str] = None
    status: str
    strategy_name: Optional[str] = None
    error_type: Optional[str] = None
    created_at: str
    latency_ms: Optional[float] = None  # parsed from metrics_json if present


class ErrorTypeStats(BaseModel):
    error_type: Optional[str]
    count: int
    last_seen: Optional[str] = None


class StrategyStats(BaseModel):
    strategy_name: Optional[str]
    target_module: Optional[str]
    total_executions: int
    success_executions: int
    failed_executions: int
    success_rate: float
    failed_rate: float


class ReflectorInsights(BaseModel):
    summary: TaskSummary
    worst_nodes: List[NodeErrorStats]
    worst_modules: List[ModuleErrorStats]
    top_error_types: List[ErrorTypeStats]
    strategy_stats: List[StrategyStats]


# ---------- Helpers ---------- #

def _safe_div(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _parse_latency_ms(metrics_json: Optional[str]) -> Optional[float]:
    """
    Try to pull a 'latency_ms' or 'duration_ms' value from metrics_json.
    Returns None if not present or invalid.
    """
    if not metrics_json:
        return None
    try:
        data = json.loads(metrics_json)
        if isinstance(data, dict):
            if "latency_ms" in data and isinstance(data["latency_ms"], (int, float)):
                return float(data["latency_ms"])
            if "duration_ms" in data and isinstance(data["duration_ms"], (int, float)):
                return float(data["duration_ms"])
    except Exception:
        return None
    return None


# ---------- Existing Endpoints (v0) ---------- #

@app.get("/reflector/summary", response_model=TaskSummary)
def reflector_summary():
    """
    High-level summary of tasks in the system.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) AS c FROM tasks")
        total = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM tasks WHERE final_status = 'SUCCESS'")
        success = cur.fetchone()["c"]

        cur.execute("SELECT COUNT(*) AS c FROM tasks WHERE final_status = 'FAILED'")
        failed = cur.fetchone()["c"]

        success_rate = _safe_div(success, total)

        logger.info(
            "[REFLECTOR_SUMMARY] total=%s success=%s failed=%s success_rate=%.3f",
            total, success, failed, success_rate,
        )

        return TaskSummary(
            total_tasks=total,
            success_count=success,
            failed_count=failed,
            success_rate=success_rate,
        )


@app.get("/reflector/nodes/errors", response_model=List[NodeErrorStats])
def reflector_node_errors():
    """
    Error rates per node based on task_executions.status.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                target_node,
                COUNT(*) AS total_executions,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_executions
            FROM task_executions
            WHERE target_node IS NOT NULL
            GROUP BY target_node
            ORDER BY failed_executions DESC
            """
        )
        rows = cur.fetchall()

        results: List[NodeErrorStats] = []
        for row in rows:
            node_name = row["target_node"]
            total = row["total_executions"]
            failed = row["failed_executions"] or 0
            failed_rate = _safe_div(failed, total)

            results.append(
                NodeErrorStats(
                    node_name=node_name,
                    total_executions=total,
                    failed_executions=failed,
                    failed_rate=failed_rate,
                )
            )

        logger.info("[REFLECTOR_NODES_ERRORS] rows=%s", len(results))
        return results


@app.get("/reflector/modules/errors", response_model=List[ModuleErrorStats])
def reflector_module_errors():
    """
    Error rates per module (target_module) based on task_executions.status.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                target_module,
                COUNT(*) AS total_executions,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_executions
            FROM task_executions
            WHERE target_module IS NOT NULL
            GROUP BY target_module
            ORDER BY failed_executions DESC
            """
        )
        rows = cur.fetchall()

        results: List[ModuleErrorStats] = []
        for row in rows:
            module_name = row["target_module"]
            total = row["total_executions"]
            failed = row["failed_executions"] or 0
            failed_rate = _safe_div(failed, total)

            results.append(
                ModuleErrorStats(
                    module_name=module_name,
                    total_executions=total,
                    failed_executions=failed,
                    failed_rate=failed_rate,
                )
            )

        logger.info("[REFLECTOR_MODULES_ERRORS] rows=%s", len(results))
        return results


@app.get("/reflector/tasks/recent_failures", response_model=List[FailedTask])
def reflector_recent_failures(limit: int = 50):
    """
    List the most recent failed tasks from the tasks table.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                task_uuid,
                high_level_type,
                final_status,
                error_type,
                created_at
            FROM tasks
            WHERE final_status = 'FAILED'
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        )

        rows = cur.fetchall()
        results: List[FailedTask] = []

        for row in rows:
            results.append(
                FailedTask(
                    task_uuid=row["task_uuid"],
                    high_level_type=row["high_level_type"],
                    final_status=row["final_status"],
                    error_type=row["error_type"],
                    created_at=row["created_at"],
                )
            )

        logger.info("[REFLECTOR_RECENT_FAILURES] count=%s", len(results))
        return results


# ---------- New v1 Endpoints ---------- #

@app.get("/reflector/executions/recent", response_model=List[ExecutionOverview])
def reflector_recent_executions(limit: int = 50):
    """
    Recent executions joined with task-level info.
    This is the main feed for the Reflector LLM to analyse patterns.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                te.id AS execution_id,
                t.task_uuid AS task_uuid,
                t.high_level_type AS high_level_type,
                te.target_module AS target_module,
                te.target_node AS target_node,
                te.status AS status,
                te.strategy_name AS strategy_name,
                t.error_type AS error_type,
                te.metrics_json AS metrics_json,
                te.created_at AS created_at
            FROM task_executions te
            LEFT JOIN tasks t ON t.id = te.task_id
            ORDER BY datetime(te.created_at) DESC
            LIMIT ?
            """,
            (limit,),
        )

        rows = cur.fetchall()
        results: List[ExecutionOverview] = []

        for row in rows:
            latency_ms = _parse_latency_ms(row["metrics_json"]) if "metrics_json" in row.keys() else None

            results.append(
                ExecutionOverview(
                    execution_id=row["execution_id"],
                    task_uuid=row["task_uuid"],
                    high_level_type=row["high_level_type"],
                    target_module=row["target_module"],
                    target_node=row["target_node"],
                    status=row["status"],
                    strategy_name=row["strategy_name"] if "strategy_name" in row.keys() else None,
                    error_type=row["error_type"],
                    created_at=row["created_at"],
                    latency_ms=latency_ms,
                )
            )

        logger.info("[REFLECTOR_RECENT_EXECUTIONS] count=%s", len(results))
        return results


@app.get("/reflector/errors/by_type", response_model=List[ErrorTypeStats])
def reflector_errors_by_type(limit: int = 20):
    """
    Aggregate errors by error_type from the tasks table.
    Useful for seeing which failure modes dominate.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT
                error_type,
                COUNT(*) AS cnt,
                MAX(created_at) AS last_seen
            FROM tasks
            WHERE final_status = 'FAILED'
            GROUP BY error_type
            ORDER BY cnt DESC
            LIMIT ?
            """,
            (limit,),
        )

        rows = cur.fetchall()
        results: List[ErrorTypeStats] = []

        for row in rows:
            results.append(
                ErrorTypeStats(
                    error_type=row["error_type"],
                    count=row["cnt"],
                    last_seen=row["last_seen"],
                )
            )

        logger.info("[REFLECTOR_ERRORS_BY_TYPE] count=%s", len(results))
        return results


@app.get("/reflector/strategies/summary", response_model=List[StrategyStats])
def reflector_strategy_summary(limit: int = 50):
    """
    Basic strategy-level performance stats, based on task_executions.strategy_name.
    If you haven't added strategy_name yet, either add it to schema or disable this endpoint.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        # Note: strategy_name may be NULL for many rows; that's fine.
        cur.execute(
            """
            SELECT
                strategy_name,
                target_module,
                COUNT(*) AS total_executions,
                SUM(CASE WHEN status = 'SUCCESS' THEN 1 ELSE 0 END) AS success_executions,
                SUM(CASE WHEN status = 'FAILED' THEN 1 ELSE 0 END) AS failed_executions
            FROM task_executions
            GROUP BY strategy_name, target_module
            ORDER BY failed_executions DESC, total_executions DESC
            LIMIT ?
            """,
            (limit,),
        )

        rows = cur.fetchall()
        results: List[StrategyStats] = []

        for row in rows:
            total = row["total_executions"]
            success = row["success_executions"] or 0
            failed = row["failed_executions"] or 0

            results.append(
                StrategyStats(
                    strategy_name=row["strategy_name"],
                    target_module=row["target_module"],
                    total_executions=total,
                    success_executions=success,
                    failed_executions=failed,
                    success_rate=_safe_div(success, total),
                    failed_rate=_safe_div(failed, total),
                )
            )

        logger.info("[REFLECTOR_STRATEGY_SUMMARY] count=%s", len(results))
        return results


@app.get("/reflector/insights", response_model=ReflectorInsights)
def reflector_insights():
    """
    One-shot JSON bundle that the Reflector LLM can consume to write
    'lessons learned' and propose experiments.

    This does NOT do any LLM work itself; it's the analytic substrate.
    """
    summary = reflector_summary()
    worst_nodes = reflector_node_errors()
    worst_modules = reflector_module_errors()
    top_error_types = reflector_errors_by_type()
    strategy_stats = reflector_strategy_summary()

    insights = ReflectorInsights(
        summary=summary,
        worst_nodes=worst_nodes,
        worst_modules=worst_modules,
        top_error_types=top_error_types,
        strategy_stats=strategy_stats,
    )

    logger.info(
        "[REFLECTOR_INSIGHTS] total_tasks=%s, nodes=%s, modules=%s, errors=%s, strategies=%s",
        summary.total_tasks,
        len(worst_nodes),
        len(worst_modules),
        len(top_error_types),
        len(strategy_stats),
    )
    return insights


# ---------- Dev-only: local run ---------- #

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "reflector_service:app",
        host="0.0.0.0",
        port=5081,
        reload=True,
    )
