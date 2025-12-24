# orchestrator/reflector/service.py

import os
import json
import logging
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI
from pydantic import BaseModel

from orchestrator.db.db_manager import get_connection  # reuse same DB helper
from orchestrator.reflector_evals.router import router as evals_router  # Harness v1 router

logger = logging.getLogger("reflector")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger.setLevel(logging.INFO)

# --- Architect config and helper --- #
ARCHITECT_COUNCIL_URL = os.getenv(
    "ARCHITECT_COUNCIL_URL",
    "http://127.0.0.1:8012/architect/propose",
).rstrip("/")
ENABLE_ARCHITECT = os.getenv("ENABLE_ARCHITECT", "true").lower() in ("1", "true", "yes", "on")


def _call_architect_for_proposal(insights: dict, latest_lesson_id: int) -> Optional[Dict[str, Any]]:
    """
    Ask Architect to generate a safe improvement proposal from the current insights.
    Returns proposal dict (matching ReflectorProposalInput shape) or None on failure.
    """
    if not ENABLE_ARCHITECT:
        return None

    payload = {
        "insights": insights,
        "latest_lesson_id": latest_lesson_id,
    }

    try:
        r = requests.post(ARCHITECT_COUNCIL_URL, json=payload, timeout=120)
        if not (200 <= r.status_code < 300):
            logger.warning("[ARCHITECT_CALL] rejected status=%s body=%s", r.status_code, (r.text or "")[:300])
            return None
        data = r.json()
        # Architect returns: {"proposal": {...}}
        proposal = data.get("proposal")
        if not isinstance(proposal, dict):
            logger.warning("[ARCHITECT_CALL] invalid response shape: %s", str(data)[:300])
            return None
        return proposal
    except Exception as e:
        logger.warning("[ARCHITECT_CALL] error: %s", e)
        return None


app = FastAPI(
    title="Bobiverse Reflector v1",
    description="Analytics and basic self-reflection over Bobiverse task history.",
    version="1.0.0",
)

# ---- Health Endpoint ----
@app.get("/health")
def health():
    return {"status": "ok", "service": "reflector", "version": "1.0.0"}

# ---- Harness v1 (Evals) ----
app.include_router(evals_router)

# ---------- Core Models (existing) ---------- #


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
    task_uuid: Optional[str]
    high_level_type: Optional[str] = None
    target_module: Optional[str] = None
    target_node: Optional[str] = None
    status: str
    strategy_name: Optional[str] = None
    error_type: Optional[str] = None
    created_at: str
    latency_ms: Optional[float] = None  # reserved for future metrics_json usage


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
    recent_failures: List[FailedTask]


class ReflectorLessonInput(BaseModel):
    summary_text: str
    source: str = "manual"
    tags: Optional[List[str]] = None


class ReflectorLesson(BaseModel):
    id: int
    created_at: str
    summary_text: str
    raw_snapshot_json: dict
    source: Optional[str] = None
    tags: List[str] = []


class ReflectorProposalInput(BaseModel):
    proposal_uuid: str
    proposal_type: str  # e.g. PROMPT_TWEAK, ROUTING_POLICY
    target_module: str  # e.g. dev_council
    motivation_lesson_id: Optional[int] = None
    risk_score: int = 3  # 1–5
    description: str  # 1–2 sentence summary
    action_payload: Dict[str, Any]
    source: str = "llm"  # e.g. 'llm-deepseek', 'heuristic'


class ReflectorProposal(BaseModel):
    id: int
    created_at: str
    proposal_uuid: str
    proposal_type: str
    target_module: str
    motivation_lesson_id: Optional[int] = None
    risk_score: int
    description: str
    action_payload: Dict[str, Any]
    source: Optional[str] = None
    status: str
    applied_at: Optional[str] = None


class ReflectorRunRequest(BaseModel):
    module: Optional[str] = None  # e.g. "dev_council"
    limit: int = 200  # hint for scope; currently used for failure snapshot


# ---------- Helpers ---------- #


def _safe_div(numerator: int, denominator: int) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _has_column(table: str, column: str) -> bool:
    """
    Check if a column exists on a table in SQLite.
    This lets us add strategy-related endpoints safely before schema upgrades.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        cols = [row["name"] for row in cur.fetchall()]
        return column in cols


def _pack_tags(tags: Optional[List[str]]) -> Optional[str]:
    if not tags:
        return None
    cleaned = [t.strip() for t in tags if t and t.strip()]
    return ",".join(cleaned) if cleaned else None


def _unpack_tags(tag_str: Optional[str]) -> List[str]:
    if not tag_str:
        return []
    return [t.strip() for t in tag_str.split(",") if t.strip()]


# ---------- Existing Endpoints (kept) ---------- #


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
    Used as the main feed for the future Reflector brain.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        # We intentionally *don't* reference strategy_name/metrics_json here
        # so this endpoint works even before schema upgrades.
        cur.execute(
            """
            SELECT
                te.id AS execution_id,
                t.task_uuid AS task_uuid,
                t.high_level_type AS high_level_type,
                te.target_module AS target_module,
                te.target_node AS target_node,
                te.status AS status,
                t.error_type AS error_type,
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
            results.append(
                ExecutionOverview(
                    execution_id=row["execution_id"],
                    task_uuid=row["task_uuid"],
                    high_level_type=row["high_level_type"],
                    target_module=row["target_module"],
                    target_node=row["target_node"],
                    status=row["status"],
                    strategy_name=None,  # reserved for future
                    error_type=row["error_type"],
                    created_at=row["created_at"],
                    latency_ms=None,  # reserved for future metrics_json
                )
            )

        logger.info("[REFLECTOR_RECENT_EXECUTIONS] count=%s", len(results))
        return results


@app.get("/reflector/errors/by_type", response_model=List[ErrorTypeStats])
def reflector_errors_by_type(limit: int = 50):
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
    This endpoint safely returns [] if the 'strategy_name' column doesn't exist yet.
    """
    if not _has_column("task_executions", "strategy_name"):
        logger.info("[REFLECTOR_STRATEGY_SUMMARY] 'strategy_name' column missing; returning empty list")
        return []

    with get_connection() as conn:
        cur = conn.cursor()

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
def reflector_insights(limit_failures: int = 50):
    """
    One-shot JSON bundle that the future Reflector LLM agent can consume
    to write 'lessons learned' and propose experiments.
    No LLM work happens here; this is analytics only.
    """
    summary = reflector_summary()
    worst_nodes = reflector_node_errors()
    worst_modules = reflector_module_errors()
    top_error_types = reflector_errors_by_type()
    strategy_stats = reflector_strategy_summary()
    recent_failures = reflector_recent_failures(limit=limit_failures)

    logger.info(
        "[REFLECTOR_INSIGHTS] total_tasks=%s nodes=%s modules=%s errors=%s strategies=%s recent_failures=%s",
        summary.total_tasks,
        len(worst_nodes),
        len(worst_modules),
        len(top_error_types),
        len(strategy_stats),
        len(recent_failures),
    )

    return ReflectorInsights(
        summary=summary,
        worst_nodes=worst_nodes,
        worst_modules=worst_modules,
        top_error_types=top_error_types,
        strategy_stats=strategy_stats,
        recent_failures=recent_failures,
    )


@app.post("/reflector/lessons", response_model=ReflectorLesson)
def create_reflector_lesson(payload: ReflectorLessonInput):
    """
    Capture a Reflector 'lesson':
      - Takes a human/agent summary_text + source/tags.
      - Captures the current /reflector/insights snapshot.
      - Stores both in reflector_lessons.
    """
    insights = reflector_insights(limit_failures=50)
    snapshot_json = insights.model_dump()

    with get_connection() as conn:
        cur = conn.cursor()
        tags_str = _pack_tags(payload.tags)

        cur.execute(
            """
            INSERT INTO reflector_lessons (summary_text, raw_snapshot_json, source, tags)
            VALUES (?, ?, ?, ?)
            """,
            (
                payload.summary_text,
                json.dumps(snapshot_json),
                payload.source,
                tags_str,
            ),
        )
        lesson_id = cur.lastrowid

        cur.execute(
            """
            SELECT id, created_at, summary_text, raw_snapshot_json, source, tags
            FROM reflector_lessons
            WHERE id = ?
            """,
            (lesson_id,),
        )
        row = cur.fetchone()

    logger.info("[REFLECTOR_LESSON_CREATED] id=%s source=%s tags=%s", row["id"], row["source"], row["tags"])

    return ReflectorLesson(
        id=row["id"],
        created_at=row["created_at"],
        summary_text=row["summary_text"],
        raw_snapshot_json=json.loads(row["raw_snapshot_json"]),
        source=row["source"],
        tags=_unpack_tags(row["tags"]),
    )


@app.get("/reflector/lessons/recent", response_model=List[ReflectorLesson])
def get_recent_reflector_lessons(limit: int = 20):
    """
    Return the most recent reflector lessons, newest first.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, created_at, summary_text, raw_snapshot_json, source, tags
            FROM reflector_lessons
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()

    lessons: List[ReflectorLesson] = []
    for row in rows:
        lessons.append(
            ReflectorLesson(
                id=row["id"],
                created_at=row["created_at"],
                summary_text=row["summary_text"],
                raw_snapshot_json=json.loads(row["raw_snapshot_json"]),
                source=row["source"],
                tags=_unpack_tags(row["tags"]),
            )
        )

    logger.info("[REFLECTOR_LESSONS_RECENT] count=%s", len(lessons))
    return lessons


@app.post("/reflector/proposals", response_model=ReflectorProposal)
def create_reflector_proposal(payload: ReflectorProposalInput):
    """
    Store a structured proposal generated by the Reflector Brain (or manually).
    The payload's action_payload is stored as JSON text.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO reflector_proposals (
                proposal_uuid,
                proposal_type,
                target_module,
                motivation_lesson_id,
                risk_score,
                description,
                action_payload_json,
                source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.proposal_uuid,
                payload.proposal_type,
                payload.target_module,
                payload.motivation_lesson_id,
                payload.risk_score,
                payload.description,
                json.dumps(payload.action_payload),
                payload.source,
            ),
        )
        proposal_id = cur.lastrowid

        cur.execute(
            """
            SELECT id, created_at, proposal_uuid, proposal_type, target_module,
                   motivation_lesson_id, risk_score, description,
                   action_payload_json, source, status, applied_at
            FROM reflector_proposals
            WHERE id = ?
            """,
            (proposal_id,),
        )
        row = cur.fetchone()

    logger.info("[REFLECTOR_PROPOSAL_CREATED] id=%s type=%s target_module=%s", row["id"], row["proposal_type"], row["target_module"])

    return ReflectorProposal(
        id=row["id"],
        created_at=row["created_at"],
        proposal_uuid=row["proposal_uuid"],
        proposal_type=row["proposal_type"],
        target_module=row["target_module"],
        motivation_lesson_id=row["motivation_lesson_id"],
        risk_score=row["risk_score"],
        description=row["description"],
        action_payload=json.loads(row["action_payload_json"]),
        source=row["source"],
        status=row["status"],
        applied_at=row["applied_at"],
    )


@app.get("/reflector/proposals/recent", response_model=List[ReflectorProposal])
def get_recent_reflector_proposals(limit: int = 20):
    """
    Return the most recent proposals, newest first.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, created_at, proposal_uuid, proposal_type, target_module,
                   motivation_lesson_id, risk_score, description,
                   action_payload_json, source, status, applied_at
            FROM reflector_proposals
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()

    proposals: List[ReflectorProposal] = []
    for row in rows:
        proposals.append(
            ReflectorProposal(
                id=row["id"],
                created_at=row["created_at"],
                proposal_uuid=row["proposal_uuid"],
                proposal_type=row["proposal_type"],
                target_module=row["target_module"],
                motivation_lesson_id=row["motivation_lesson_id"],
                risk_score=row["risk_score"],
                description=row["description"],
                action_payload=json.loads(row["action_payload_json"]),
                source=row["source"],
                status=row["status"],
                applied_at=row["applied_at"],
            )
        )

    logger.info("[REFLECTOR_PROPOSALS_RECENT] count=%s", len(proposals))
    return proposals


@app.post("/reflector/run")
def reflector_run(body: ReflectorRunRequest):
    """
    Trigger a Reflector analysis cycle.

    This is called by `./bobctl reflector-run`.

    v1 behaviour:
      - Generate an analytics snapshot (via reflector_insights()).
      - Store it as an auto-generated lesson in reflector_lessons.
      - (Future) Optionally generate proposals via an LLM.
      - Return a compact summary including how many lessons/proposals were created.
    """
    limit_failures = max(1, min(body.limit, 500))
    insights = reflector_insights(limit_failures=limit_failures)
    snapshot_json = insights.model_dump()

    summary_obj = insights.summary
    module_label = body.module or "all"
    summary_text = (
        f"Auto Reflector run over last {limit_failures} failures "
        f"(module={module_label}). "
        f"Total tasks={summary_obj.total_tasks}, "
        f"success={summary_obj.success_count}, "
        f"failed={summary_obj.failed_count}, "
        f"success_rate={summary_obj.success_rate:.3f}."
    )

    with get_connection() as conn:
        cur = conn.cursor()
        tags = ["auto-run", f"module:{module_label}"]
        tags_str = _pack_tags(tags)

        cur.execute(
            """
            INSERT INTO reflector_lessons (summary_text, raw_snapshot_json, source, tags)
            VALUES (?, ?, ?, ?)
            """,
            (
                summary_text,
                json.dumps(snapshot_json),
                "auto-run",
                tags_str,
            ),
        )
        lesson_id = cur.lastrowid

    proposals_created = 0

    proposal_obj = _call_architect_for_proposal(snapshot_json, lesson_id)
    if proposal_obj:
        try:
            with get_connection() as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO reflector_proposals (
                        proposal_uuid,
                        proposal_type,
                        target_module,
                        motivation_lesson_id,
                        risk_score,
                        description,
                        action_payload_json,
                        source,
                        status
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
                    """,
                    (
                        proposal_obj.get("proposal_uuid"),
                        proposal_obj.get("proposal_type"),
                        proposal_obj.get("target_module"),
                        lesson_id,
                        int(proposal_obj.get("risk_score", 3)),
                        proposal_obj.get("description"),
                        json.dumps(proposal_obj.get("action_payload") or {}),
                        proposal_obj.get("source") or "llm-architect-bob",
                    ),
                )
            proposals_created = 1
        except Exception as e:
            logger.warning("[ARCHITECT_STORE] failed to store proposal: %s", e)

    logger.info("[REFLECTOR_RUN] module=%s limit=%s lesson_id=%s", body.module, body.limit, lesson_id)

    return {
        "status": "ok",
        "module": body.module,
        "limit": body.limit,
        "execution_id": None,
        "task_uuid": None,
        "lessons_created": 1,
        "proposals_created": proposals_created,
        "summary": summary_text,
    }


# ---------- Dev-only: local run ---------- #

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "orchestrator.reflector.service:app",
        host="0.0.0.0",
        port=5081,
        reload=True,
    )
