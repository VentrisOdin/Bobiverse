# orchestrator/reflector_service.py

import logging
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel

from db.db_manager import get_connection  # reuse same DB connection helper

logger = logging.getLogger("reflector")
logger.setLevel(logging.INFO)


app = FastAPI(
    title="Bobiverse Reflector v0",
    description="Read-only analytics over Bobiverse task history.",
    version="0.1.0",
)


# ---------- Models ---------- #

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
    high_level_type: str | None = None
    final_status: str | None = None
    error_type: str | None = None
    created_at: str  # ISO string from DB


# ---------- Helpers ---------- #

def _safe_div(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


# ---------- Endpoints ---------- #

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


# ---------- Dev-only: local run ---------- #

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "reflector_service:app",
        host="0.0.0.0",
        port=5081,
        reload=True,
    )
