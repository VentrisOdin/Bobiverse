

import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Literal
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from orchestrator.db.db_manager import (
    init_db,
    create_task,
    get_task_by_uuid,
    update_task_status,
    create_task_execution,
    complete_task_execution,
    get_executions_for_task,
    list_recent_tasks,
    list_recent_executions,
    create_policy_proposal,
    list_policy_proposals,
    get_policy_proposal_by_uuid,
    update_policy_proposal_status,
    get_connection,
)

from orchestrator.models import (
    NodeRegistration,
    NodeHeartbeat,
    NodeInfo,
    NodeHealth,
    TaskSubmit,
    TaskInfo,
    TaskResult,
    DbTaskCreate,
    PolicyProposalCreate,
    PolicyProposalRecord,
)

from orchestrator.teacher_router import call_teacher
from orchestrator.ops_client import get_ops_hints
import threading
from orchestrator.ops_reporter import run_forever
from orchestrator.memory_client import write_event
from dotenv import load_dotenv
import uuid
import json


# ---------- Dev Council Models ---------- #

class DevTaskCreate(BaseModel):
    """
    Payload for creating a Dev Council task via /tasks/dev.
    This is intentionally simple and matches bobctl submit-dev.
    """
    description: str
    details: Optional[str] = None
    submitted_by: str = "bobctl"
    priority: Literal["low", "normal", "high"] = "normal"


class DevTaskNextResponse(BaseModel):
    task_uuid: str
    input_payload: Dict[str, Any]
    submitted_by: str
    created_at: str
    execution_id: int


class DevTaskResultIn(BaseModel):
    execution_id: int
    status: Literal["success", "partial", "failed"]
    output_summary: str
    full_response: Optional[Dict[str, Any]] = None


class ReflectorExecution(BaseModel):
    id: int
    task_id: int
    task_uuid: str
    high_level_type: Optional[str] = None
    target_module: Optional[str] = None
    target_node: Optional[str] = None
    strategy_name: Optional[str] = None
    status: Optional[str] = None
    output_summary: Optional[str] = None
    error_type: Optional[str] = None
    latency_ms: Optional[int] = None
    metrics_json: Optional[Dict[str, Any]] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# ---------- Knowledge Council Models ---------- #

class KnowledgeTaskCreate(BaseModel):
    """
    Payload for creating a Knowledge Council task via /tasks/knowledge.
    """
    question: str
    extra_context: Optional[str] = None
    submitted_by: str = "bobctl"
    priority: Literal["low", "normal", "high"] = "normal"


class KnowledgeTaskNextResponse(BaseModel):
    task_uuid: str
    input_payload: Dict[str, Any]
    submitted_by: str
    created_at: str
    execution_id: int



class KnowledgeTaskResultIn(BaseModel):
    execution_id: int
    status: Literal["success", "partial", "failed"]
    output_summary: str
    full_response: Optional[Dict[str, Any]] = None

# ---------- Teacher Council Models ---------- #

class TeacherTaskCreate(BaseModel):
    """
    Payload for creating a Teacher Council task via /tasks/teacher.
    """
    question: str
    max_sources: int = 6
    domains_allow: Optional[List[str]] = None
    include_snippets: bool = True
    submitted_by: str = "bobctl"
    priority: Literal["low", "normal", "high"] = "normal"

# Load .env if present
load_dotenv()

# ---------------- Logging Setup ---------------- #

LOG_DIR = Path.home() / "bobiverse" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "orchestrator.log"

logger = logging.getLogger("prime_bob")
logger.setLevel(logging.INFO)

handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=5_000_000,   # ~5MB per file
    backupCount=5,        # keep multiple historical logs
)

formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s"
)
handler.setFormatter(formatter)

# Prevent double logging
if not logger.handlers:
    logger.addHandler(handler)

logger.info("Prime Bob orchestrator starting…")

ORCHESTRATOR_NODE_NAME = os.getenv("ORCHESTRATOR_NODE_NAME", "prime-bob")
ORCHESTRATOR_PORT = int(os.getenv("ORCHESTRATOR_PORT", "5080"))

# Consider a node "stale" if no heartbeat within this many seconds
STALE_THRESHOLD_SECONDS = 20

app = FastAPI(
    title="Bobiverse Orchestrator",
    description="Prime Bob – central brain for coordinating nodes and councils.",
    version="0.1.0",
)



@app.on_event("startup")
async def startup_event():
    # Ensure the SQLite DB and tables exist
    init_db()
    logger.info("Database initialised.")

    # Start ops_reporter in a daemon thread
    try:
        t = threading.Thread(target=run_forever, daemon=True)
        t.start()
        logger.info("Ops server reporter enabled.")
    except Exception as e:
        logger.warning(f"Failed to start ops server reporter: {e}")


# In-memory node registry (Phase 1: keep it simple)
NODE_REGISTRY: Dict[str, NodeInfo] = {}

TASKS: Dict[int, TaskInfo] = {}
TASK_COUNTER: int = 0

# Map in-memory task.id -> DB task_uuid
TASK_DB_UUIDS: Dict[int, str] = {}

# NEW: map in-memory task.id -> DB execution_id
TASK_DB_EXECUTION_IDS: Dict[int, int] = {}


# ---------- Helper ---------- #

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _choose_node_for_task() -> Optional[str]:
    """
    Very simple heuristic: choose the node with the lowest reported load.
    If no node has load set, just pick the first one.
    Returns the node name or None if there are no nodes.
    """
    if not NODE_REGISTRY:
        return None

    ops_hints = get_ops_hints()  # node_id -> {routable, health_score, ...}

    # Exclude unroutable nodes if Ops Bob has an opinion
    candidates = []
    for n in NODE_REGISTRY.values():
        hint = ops_hints.get(n.name)
        if hint is not None and hint.get("routable") is False:
            continue
        candidates.append(n)

    if not candidates:
        return None  # Everyone is unroutable (or no nodes)

    # Existing behaviour: pick lowest load, but use Ops health as a tie-breaker if present
    def score(node: NodeInfo):
        hint = ops_hints.get(node.name, {})
        health = float(hint.get("health_score", 0.0))
        load = node.load if node.load is not None else 999.0
        # Higher health is better, lower load is better
        return (-health, load, node.name.lower())

    chosen = sorted(candidates, key=score)[0]
    return chosen.name


def choose_node_for_capability(task_type: str) -> Optional[str]:
    """
    Return a node that advertises capability matching the high_level_type.
    E.g. task_type='dev' => node with 'dev' in node.capabilities.

    If none match, fall back to lowest-load node.
    """
    if not NODE_REGISTRY:
        return None

    ops_hints = get_ops_hints()

    capable_nodes = [
        n for n in NODE_REGISTRY.values()
        if task_type in n.capabilities
    ]

    # Filter unroutable (only if Ops Bob returned a hint for that node)
    capable_nodes = [
        n for n in capable_nodes
        if not (ops_hints.get(n.name) is not None and ops_hints.get(n.name, {}).get("routable") is False)
    ]

    if capable_nodes:
        def score(node: NodeInfo):
            hint = ops_hints.get(node.name, {})
            health = float(hint.get("health_score", 0.0))
            load = node.load if node.load is not None else 999.0
            return (-health, load, node.name.lower())

        return sorted(capable_nodes, key=score)[0].name

    # Fallback: use generic selector (which already filters unroutable)
    return _choose_node_for_task()


# ---------- Routes ---------- #

@app.get("/health")
def health():
    """Simple health check so you can curl the orchestrator."""
    logger.info("[HEALTH] Health check requested")
    return {
        "status": "ok",
        "orchestrator": ORCHESTRATOR_NODE_NAME,
        "nodes_known": len(NODE_REGISTRY),
        "time": _utc_now().isoformat(),
    }


@app.post("/register")
def register_node(payload: NodeRegistration):
    """
    Called by node_agent at startup.
    Creates/updates the node entry in the registry.
    """
    logger.info(f"[REGISTER] Node '{payload.name}' ({payload.role}) @ {payload.tailscale_ip}")

    node = NodeInfo(
        name=payload.name,
        role=payload.role,
        tailscale_ip=payload.tailscale_ip,
        capabilities=payload.capabilities or [],
        last_seen=_utc_now(),
        load=None,
        free_memory_mb=None,
        active_councils=[],
    )
    NODE_REGISTRY[payload.name] = node
    return {"status": "registered", "node": node}


@app.post("/heartbeat")
def heartbeat(payload: NodeHeartbeat):
    """
    Called periodically by node_agent (e.g. every 5–10 seconds).
    Updates metrics + last_seen.
    """
    if payload.name not in NODE_REGISTRY:
        logger.warning(f"[HEARTBEAT] Unknown node '{payload.name}' – heartbeat rejected.")
        raise HTTPException(
            status_code=404,
            detail=f"Node '{payload.name}' not registered. Call /register first.",
        )

    node = NODE_REGISTRY[payload.name]
    node.last_seen = _utc_now()

    if payload.load is not None:
        node.load = payload.load
    if payload.free_memory_mb is not None:
        node.free_memory_mb = payload.free_memory_mb
    if payload.active_councils is not None:
        node.active_councils = payload.active_councils

    NODE_REGISTRY[payload.name] = node

    logger.info(
        f"[HEARTBEAT] Node '{payload.name}' load={payload.load}, free_mem={payload.free_memory_mb}MB"
    )

    return {"status": "heartbeat_ok", "node": node}


@app.get("/nodes/health", response_model=List[NodeHealth])
def nodes_health():
    """
    Return a simple health view of all known nodes based on last_seen.
    A node is 'online' if its last_seen is within STALE_THRESHOLD_SECONDS,
    otherwise 'stale'.
    """
    now = _utc_now()
    results: List[NodeHealth] = []

    for node in NODE_REGISTRY.values():
        delta = now - node.last_seen
        is_online = delta.total_seconds() <= STALE_THRESHOLD_SECONDS
        status = "online" if is_online else "stale"

        results.append(
            NodeHealth(
                name=node.name,
                status=status,
                last_seen=node.last_seen,
                load=node.load,
                free_memory_mb=node.free_memory_mb,
            )
        )

    logger.info("[NODES_HEALTH] Report generated for %d nodes", len(results))
    return results


@app.get("/nodes", response_model=List[NodeInfo])
def list_nodes():
    """
    Get a list of all known nodes.
    """
    return sorted(
        NODE_REGISTRY.values(),
        key=lambda n: n.name.lower(),
    )


@app.get("/nodes/{name}", response_model=NodeInfo)
def get_node(name: str):
    """
    Get details of a specific node.
    """
    if name not in NODE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Node '{name}' not found.")
    return NODE_REGISTRY[name]


@app.delete("/nodes/{name}")
def drop_node(name: str):
    """
    Manually remove a node from the registry (e.g. retired machine).
    """
    if name in NODE_REGISTRY:
        del NODE_REGISTRY[name]
        return {"status": "deleted", "name": name}
    raise HTTPException(status_code=404, detail=f"Node '{name}' not found.")


@app.post("/submit_task", response_model=TaskInfo)
def submit_task(payload: TaskSubmit):
    """
    Submit a simple test task. For Phase 1.5 this just routes to a node
    and stores everything in memory, and now also logs to SQLite.
    """
    global TASK_COUNTER

    # Choose target node
    target_name = payload.target_node

    if target_name is not None:
        if target_name not in NODE_REGISTRY:
            raise HTTPException(
                status_code=404,
                detail=f"Target node '{target_name}' not found.",
            )
    else:
        # New: capability-aware routing
        target_name = choose_node_for_capability(payload.high_level_type)
        if target_name is None:
            raise HTTPException(
                status_code=503,
                detail=f"No nodes available with capability '{payload.high_level_type}'.",
            )

    # --- Canonicalise high_level_type + input_payload ---

    # Default type
    high_level_type = payload.high_level_type or "generic"

    # Legacy support: if no input_payload provided, wrap description
    if payload.input_payload is not None:
        input_payload = dict(payload.input_payload)  # shallow copy
    else:
        input_payload = {}
        if payload.description:
            input_payload["description"] = payload.description

    # Make sure there's always a human-readable description
    description = payload.description or input_payload.get("description") or ""

    TASK_COUNTER += 1
    now = _utc_now()
    task = TaskInfo(
        id=TASK_COUNTER,
        description=description,
        target_node=target_name,
        status="pending",
        created_at=now,
        updated_at=now,
        result=None,
        high_level_type=high_level_type,
        input_payload=input_payload,
    )
    TASKS[task.id] = task

    # ---------- Log into DB ----------
    try:
        db_task = create_task(
            high_level_type=high_level_type,
            input_payload=input_payload,
            submitted_by=payload.submitted_by or "user",
            is_experiment=False,
            input_hash=None,
        )
        task_uuid = db_task["task_uuid"]
        TASK_DB_UUIDS[task.id] = task_uuid

        logger.info(
            "[TASK_SUBMIT_DB] id=%s uuid=%s db_id=%s",
            task.id,
            task_uuid,
            db_task["id"],
        )
    except Exception as e:
        # We don't want DB errors to break the API in dev;
        # just log them for now.
        logger.exception("Failed to log task to DB: %s", e)

    logger.info(
        "[TASK_SUBMIT] id=%s target_node=%s type=%s desc=%s",
        task.id,
        task.target_node,
        high_level_type,
        task.description,
    )

    return task


@app.get("/tasks/next", response_model=Optional[TaskInfo])
def next_task(node_name: str):
    """
    Called by a node to fetch its next pending task.
    Marks the task as in_progress.
    Returns 200 with a TaskInfo if a task exists, or None if none.
    """
    if node_name not in NODE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not registered.")

    # Find first pending task for this node
    for task in TASKS.values():
        if task.target_node == node_name and task.status == "pending":
            task.status = "in_progress"
            task.updated_at = _utc_now()
            logger.info("[TASK_ASSIGN] id=%s -> node=%s", task.id, node_name)

            # ----- DB logging -----
            task_uuid = TASK_DB_UUIDS.get(task.id)
            if task_uuid:
                try:
                    # Update DB task status to RUNNING
                    update_task_status(
                        task_uuid=task_uuid,
                        final_status="RUNNING",
                    )

                    # Create an execution row
                    exec_row = create_task_execution(
                        task_uuid=task_uuid,
                        target_module="generic",
                        target_node=node_name,
                        strategy_name="orchestrator:queue_v1",
                    )
                    TASK_DB_EXECUTION_IDS[task.id] = exec_row["id"]

                    logger.info(
                        "[TASK_EXEC_DB_START] task_id=%s task_uuid=%s exec_id=%s",
                        task.id,
                        task_uuid,
                        exec_row["id"],
                    )
                except Exception as e:
                    logger.exception("Failed to log task execution start to DB: %s", e)

            return task

    # No tasks
    return None


@app.post("/tasks/{task_id}/result", response_model=TaskInfo)
def task_result(task_id: int, payload: TaskResult):
    """
    Node reports back the result of a task.
    """
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    task = TASKS[task_id]

    if task.target_node != payload.node_name:
        raise HTTPException(
            status_code=400,
            detail=f"Task '{task_id}' is assigned to '{task.target_node}', "
                   f"not '{payload.node_name}'.",
        )

    task.status = payload.status
    task.result = payload.result
    task.updated_at = _utc_now()

    TASKS[task_id] = task

    # ---------- DB: update task + execution ----------
    task_uuid = TASK_DB_UUIDS.get(task_id)
    exec_id = TASK_DB_EXECUTION_IDS.get(task_id)

    if task_uuid:
        final_status_db = "SUCCESS" if payload.status == "completed" else "FAILED"
        error_msg = payload.result if payload.status == "failed" else None

        # 1) Update the task row
        try:
            update_task_status(
                task_uuid=task_uuid,
                final_status=final_status_db,
                error_type=error_msg,
            )
            logger.info(
                "[TASK_RESULT_DB_STATUS] id=%s uuid=%s final_status=%s",
                task_id,
                task_uuid,
                final_status_db,
            )
        except Exception as e:
            logger.exception("Failed to update task status in DB: %s", e)

        # 2) Update the execution row (if we have one)
        if exec_id is not None:
            try:
                complete_task_execution(
                    execution_id=exec_id,
                    status=final_status_db,
                    output_summary=payload.result,
                    error_type=error_msg,
                    latency_ms=None,      # could be filled in later
                    metrics=None,
                )
                logger.info(
                    "[TASK_RESULT_DB_EXEC] id=%s uuid=%s exec_id=%s",
                    task_id,
                    task_uuid,
                    exec_id,
                )
            except Exception as e:
                logger.exception("Failed to complete task execution in DB: %s", e)

    logger.info(
        "[TASK_RESULT] id=%s node=%s status=%s",
        task.id,
        payload.node_name,
        payload.status,
    )


    # --- Memory Bob event logging (generic task result) ---
    task_uuid_for_memory = TASK_DB_UUIDS.get(task_id)

    write_event({
        "task_id": task_uuid_for_memory or f"inmem:{task_id}",
        "module": task.high_level_type or "unknown",
        "node_id": payload.node_name,
        "status": "success" if payload.status == "completed" else "failed",
        "summary": str(task.result) if task.result else f"Task {payload.status}",
        "details": {
            "execution_failed": payload.status != "completed",
        },
        "tags": [
            "auto",
            task.high_level_type or "unknown",
            payload.status,
        ],
    })

    return task


@app.get("/tasks", response_model=List[TaskInfo])
def list_tasks():
    """
    Return all tasks currently known to Prime Bob (in memory).
    """
    return sorted(TASKS.values(), key=lambda t: t.id)


@app.get("/tasks/{task_id}", response_model=TaskInfo)
def get_task(task_id: int):
    """
    Get details of a single task.
    """
    if task_id not in TASKS:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")
    return TASKS[task_id]


# ---------- DB Task Routes (Phase 1.6) ---------- #

@app.post("/db/tasks/create")
def db_create_task(body: DbTaskCreate):
    """
    Create a task directly in the database (Phase 1.6 style).
    Returns the full task row including task_uuid.
    """
    row = create_task(
        high_level_type=body.high_level_type,
        input_payload=body.input_payload,
        submitted_by=body.submitted_by,
        is_experiment=body.is_experiment,
        input_hash=body.input_hash,
    )
    return row


@app.get("/db/tasks/{task_uuid}")
def db_get_task(task_uuid: str):
    """
    Get a task from the database by its UUID.
    """
    row = get_task_by_uuid(task_uuid)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


@app.get("/db/tasks")
def db_list_tasks(limit: int = 100):
    """
    List recent tasks from the database.
    """
    return list_recent_tasks(limit=limit)


@app.get("/db/tasks/{task_uuid}/executions")
def db_get_task_executions(task_uuid: str):
    """
    Get all execution records for a task.
    """
    return get_executions_for_task(task_uuid)


@app.get(
    "/reflector/executions/recent",
    response_model=List[ReflectorExecution],
    tags=["reflector"],
)
def get_recent_executions_for_reflector(
    module: Optional[str] = Query(
        None,
        description="Filter by target_module (e.g. 'dev_council')",
        alias="module",
    ),
    limit: int = Query(
        100,
        ge=1,
        le=500,
        description="Maximum number of executions to return (1–500).",
    ),
):
    """
    Read-only endpoint for the Reflector and analysis tools.

    Example:
      /reflector/executions/recent?module=dev_council&limit=100
    """
    try:
        rows = list_recent_executions(
            target_module=module,
            limit=limit,
        )
        return rows
    except Exception as e:
        logger.exception("Error fetching recent executions for Reflector: %s", e)
        raise HTTPException(status_code=500, detail="Failed to fetch recent executions")


# ---------- Policy Proposal Routes ---------- #

@app.post("/policies", response_model=PolicyProposalRecord)
def create_policy(body: PolicyProposalCreate):
    """
    Create a new policy proposal.
    """
    row = create_policy_proposal(
        source=body.source,
        proposal_type=body.proposal_type,
        scope=body.scope,
        payload=body.payload,
        rationale=body.rationale,
    )
    return row


@app.get("/policies", response_model=List[PolicyProposalRecord])
def list_policies(status: Optional[str] = None, limit: int = 100):
    """
    List policy proposals, optionally filtered by status.
    """
    return list_policy_proposals(status=status, limit=limit)


@app.get("/policies/{proposal_uuid}", response_model=PolicyProposalRecord)
def get_policy(proposal_uuid: str):
    """
    Get a specific policy proposal by UUID.
    """
    row = get_policy_proposal_by_uuid(proposal_uuid)
    if not row:
        raise HTTPException(status_code=404, detail="Policy proposal not found")
    return row


# ---------- Dev Council Routes ---------- #

@app.get("/dev/tasks/next", response_model=Optional[DevTaskNextResponse])
def dev_next_task(node_name: str):
    """
    Claim the next PENDING 'dev' task from the DB for the given node.

    - Picks the oldest PENDING dev task.
    - Marks it RUNNING (and, if columns exist, assigns target_node/target_module).
    - Creates a task_executions row.
    - Returns the input_payload plus execution_id.
    """
    if node_name not in NODE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not registered.")

    node = NODE_REGISTRY[node_name]
    if "dev" not in (node.capabilities or []):
        raise HTTPException(
            status_code=400,
            detail=f"Node '{node_name}' does not advertise 'dev' capability.",
        )

    with get_connection() as conn:
        cur = conn.cursor()

        # 1) Grab oldest PENDING dev task
        cur.execute(
            """
            SELECT *
            FROM tasks
            WHERE high_level_type = 'dev'
              AND (final_status IS NULL OR final_status = 'PENDING')
            ORDER BY id ASC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            # No pending dev tasks
            return None

        row_dict = dict(row)
        task_uuid = row_dict["task_uuid"]
        input_payload_raw = row_dict.get("input_payload")
        submitted_by = row_dict.get("submitted_by", "unknown")
        created_at = (
            row_dict.get("created_at")
            or row_dict.get("submitted_at")
            or row_dict.get("created")
            or row_dict.get("submitted")
            or ""
        )

        # Safely parse JSON payload
        try:
            input_payload = json.loads(input_payload_raw) if input_payload_raw else {}
        except json.JSONDecodeError:
            input_payload = {}

        # Ensure Dev Bob always has a task_id to work with
        if not input_payload.get("task_id"):
            input_payload["task_id"] = task_uuid

        # 2) Introspect tasks table columns
        cur.execute("PRAGMA table_info(tasks)")
        cols_info = cur.fetchall()
        cols = {c["name"] for c in cols_info}

        # 3) Build dynamic UPDATE depending on which columns exist
        update_parts = []
        params = []

        if "final_status" in cols:
            update_parts.append("final_status = ?")
            params.append("RUNNING")
        if "target_node" in cols:
            update_parts.append("target_node = ?")
            params.append(node_name)
        if "target_module" in cols:
            update_parts.append("target_module = ?")
            params.append("dev_council")

        if update_parts:
            sql = f"UPDATE tasks SET {', '.join(update_parts)} WHERE task_uuid = ?"
            params.append(task_uuid)
            cur.execute(sql, params)

    # 4) Create an execution record
    exec_row = create_task_execution(
        task_uuid=task_uuid,
        target_module="dev_council",
        target_node=node_name,
        strategy_name="dev:default_v1",
    )

    return DevTaskNextResponse(
        task_uuid=task_uuid,
        input_payload=input_payload,
        submitted_by=submitted_by,
        created_at=str(created_at),
        execution_id=exec_row["id"],
    )


@app.post("/dev/tasks/{task_uuid}/result")
def dev_task_result(task_uuid: str, body: DevTaskResultIn):
    """
    Node reports back the result of a Dev Council task.

    - Updates the tasks row final_status.
    - Completes the corresponding task_executions row with summary + full_response.
    """
    status_map = {
        "success": "SUCCESS",
        "partial": "PARTIAL",
        "failed": "FAILED",
    }
    final_status_db = status_map.get(body.status, "FAILED")

    error_msg = None
    if body.status == "failed":
        error_msg = body.output_summary

    # 1) Update the task row
    try:
        update_task_status(
            task_uuid=task_uuid,
            final_status=final_status_db,
            error_type=error_msg,
        )
        logger.info(
            "[DEV_TASK_RESULT_DB_STATUS] uuid=%s final_status=%s",
            task_uuid,
            final_status_db,
        )
    except Exception as e:
        logger.exception("Failed to update dev task status in DB: %s", e)

    # 2) Update the execution row
    try:
        complete_task_execution(
            execution_id=body.execution_id,
            status=final_status_db,
            output_summary=body.output_summary,
            error_type=error_msg,
            latency_ms=None,          # we can wire timing later
            metrics=body.full_response,  # store full DevTaskResponse JSON in metrics_json
        )
        logger.info(
            "[DEV_TASK_RESULT_DB_EXEC] uuid=%s exec_id=%s status=%s",
            task_uuid,
            body.execution_id,
            final_status_db,
        )
    except Exception as e:
        logger.exception("Failed to complete dev task execution in DB: %s", e)

    # --- Memory Bob event logging (Dev Council) ---
    write_event({
        "task_id": task_uuid,
        "module": "dev_council",
        "node_id": ORCHESTRATOR_NODE_NAME,
        "status": body.status,
        "summary": body.output_summary,
        "details": {
            "execution_id": body.execution_id,
            "full_response": body.full_response,
        },
        "tags": ["dev", body.status],
    })
    return {"status": "ok", "task_uuid": task_uuid, "final_status": final_status_db}


@app.post("/tasks/dev")
def create_dev_task(payload: DevTaskCreate):
    """
    Create a new 'dev' task row in the tasks table so it shows up
    and can be picked up by a node running Dev Council.
    """
    # Build what the Dev Council will see as input_payload
    input_payload: Dict[str, Any] = {
        "kind": "generic_dev_task",
        "description": payload.description,
        "details": payload.details,
        "task_type": "dev",
        "priority": payload.priority,
        "origin": {
            "submitted_by": payload.submitted_by,
            "origin_type": "bobctl",
            "source_node": "orchestrator-server",
            "source_tool": "bobctl submit-dev",
        },
    }

    # Use the existing create_task function from db_manager
    db_task = create_task(
        high_level_type="dev",
        input_payload=input_payload,
        submitted_by=payload.submitted_by,
        is_experiment=False,
        input_hash=None,
    )

    task_uuid = db_task["task_uuid"]

    logger.info(
        "[DEV_TASK_CREATE] uuid=%s priority=%s submitted_by=%s",
        task_uuid,
        payload.priority,
        payload.submitted_by,
    )

    return {
        "task_uuid": task_uuid,
        "status": "CREATED",
    }


# ---------- Knowledge Council Routes ---------- #

@app.get("/knowledge/tasks/next", response_model=Optional[KnowledgeTaskNextResponse])
def knowledge_next_task(node_name: str):
    """
    Claim the next PENDING 'knowledge' task from the DB for the given node.

    - Picks the oldest PENDING knowledge task.
    - Marks it RUNNING (and, if columns exist, assigns target_node/target_module).
    - Creates a task_executions row.
    - Returns the input_payload plus execution_id.

    Matches what node_agent.process_one_knowledge_task() expects.
    """
    if node_name not in NODE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not registered.")

    node = NODE_REGISTRY[node_name]
    if "knowledge" not in (node.capabilities or []):
        raise HTTPException(
            status_code=400,
            detail=f"Node '{node_name}' does not advertise 'knowledge' capability.",
        )

    with get_connection() as conn:
        cur = conn.cursor()

        # 1) Grab oldest PENDING knowledge task
        cur.execute(
            """
            SELECT *
            FROM tasks
            WHERE high_level_type = 'knowledge'
              AND (final_status IS NULL OR final_status = 'PENDING')
            ORDER BY id ASC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        if not row:
            # No pending knowledge tasks
            return None

        row_dict = dict(row)
        task_uuid = row_dict["task_uuid"]
        input_payload_raw = row_dict.get("input_payload")
        submitted_by = row_dict.get("submitted_by", "unknown")
        created_at = (
            row_dict.get("created_at")
            or row_dict.get("submitted_at")
            or row_dict.get("created")
            or row_dict.get("submitted")
            or ""
        )

        # Safely parse JSON payload
        try:
            input_payload = json.loads(input_payload_raw) if input_payload_raw else {}
        except json.JSONDecodeError:
            input_payload = {}

        # Ensure Knowledge Bob always has a task_id to work with
        if not input_payload.get("task_id"):
            input_payload["task_id"] = task_uuid

        # 2) Introspect tasks table columns
        cur.execute("PRAGMA table_info(tasks)")
        cols_info = cur.fetchall()
        cols = {c["name"] for c in cols_info}

        # 3) Build dynamic UPDATE depending on which columns exist
        update_parts = []
        params: List[Any] = []

        if "final_status" in cols:
            update_parts.append("final_status = ?")
            params.append("RUNNING")
        if "target_node" in cols:
            update_parts.append("target_node = ?")
            params.append(node_name)
        if "target_module" in cols:
            update_parts.append("target_module = ?")
            params.append("knowledge_council")

        if update_parts:
            sql = f"UPDATE tasks SET {', '.join(update_parts)} WHERE task_uuid = ?"
            params.append(task_uuid)
            cur.execute(sql, params)

    # 4) Create an execution record
    exec_row = create_task_execution(
        task_uuid=task_uuid,
        target_module="knowledge_council",
        target_node=node_name,
        strategy_name="knowledge:default_v1",
    )

    return KnowledgeTaskNextResponse(
        task_uuid=task_uuid,
        input_payload=input_payload,
        submitted_by=submitted_by,
        created_at=str(created_at),
        execution_id=exec_row["id"],
    )


@app.post("/knowledge/tasks/{task_uuid}/result")
def knowledge_task_result(task_uuid: str, body: KnowledgeTaskResultIn):
    """
    Node reports back the result of a Knowledge Council task.

    - Updates the tasks row final_status.
    - Completes the corresponding task_executions row with summary + full_response.
    """
    status_map = {
        "success": "SUCCESS",
        "partial": "PARTIAL",
        "failed": "FAILED",
    }
    final_status_db = status_map.get(body.status, "FAILED")

    error_msg = None
    if body.status == "failed":
        error_msg = body.output_summary

    # 1) Update the task row
    try:
        update_task_status(
            task_uuid=task_uuid,
            final_status=final_status_db,
            error_type=error_msg,
        )
        logger.info(
            "[KNOWLEDGE_TASK_RESULT_DB_STATUS] uuid=%s final_status=%s",
            task_uuid,
            final_status_db,
        )
    except Exception as e:
        logger.exception("Failed to update knowledge task status in DB: %s", e)

    # 2) Update the execution row
    try:
        complete_task_execution(
            execution_id=body.execution_id,
            status=final_status_db,
            output_summary=body.output_summary,
            error_type=error_msg,
            latency_ms=None,              # can wire timing later
            metrics=body.full_response,   # store full KnowledgeTaskResponse JSON in metrics_json
        )
        logger.info(
            "[KNOWLEDGE_TASK_RESULT_DB_EXEC] uuid=%s exec_id=%s status=%s",
            task_uuid,
            body.execution_id,
            final_status_db,
        )
    except Exception as e:
        logger.exception("Failed to complete knowledge task execution in DB: %s", e)

    # --- Memory Bob event logging (Knowledge Council) ---
    write_event({
        "task_id": task_uuid,
        "module": "knowledge_council",
        "node_id": ORCHESTRATOR_NODE_NAME,
        "status": body.status,
        "summary": body.output_summary,
        "details": {
            "execution_id": body.execution_id,
            "full_response": body.full_response,
        },
        "tags": ["knowledge", body.status],
    })
    return {"status": "ok", "task_uuid": task_uuid, "final_status": final_status_db}


@app.post("/tasks/knowledge")
def create_knowledge_task(payload: KnowledgeTaskCreate):
    """
    Create a new 'knowledge' task row in the tasks table so it shows up
    and can be picked up by a node running Knowledge Council.
    """
    # Build what the Knowledge Council will see as input_payload
    input_payload: Dict[str, Any] = {
        "kind": "knowledge_query",
        "question": payload.question,
        "extra_context": payload.extra_context,
        "task_type": "knowledge",
        "priority": payload.priority,
        "origin": {
            "submitted_by": payload.submitted_by,
            "origin_type": "bobctl",
            "source_node": "orchestrator-server",
            "source_tool": "bobctl submit-knowledge",
        },
    }

    db_task = create_task(
        high_level_type="knowledge",
        input_payload=input_payload,
        submitted_by=payload.submitted_by,
        is_experiment=False,
        input_hash=None,
    )

    task_uuid = db_task["task_uuid"]

    logger.info(
        "[KNOWLEDGE_TASK_CREATE] uuid=%s priority=%s submitted_by=%s",
        task_uuid,
        payload.priority,
        payload.submitted_by,
    )

    return {
        "task_uuid": task_uuid,
        "status": "CREATED",
    }


# ---------- Teacher Council Routes ---------- #

# ---------- Teacher Council Routes ---------- #

@app.post("/tasks/teacher")
def create_teacher_task(payload: TeacherTaskCreate):
    """
    Create and execute a Teacher Council research task immediately on the orchestrator server.
    This is different from dev/knowledge:
    - Teacher Council runs locally on the server and is the only internet gateway.
    - The orchestrator executes the research synchronously and logs results to the DB.
    """
    # 1) Build input payload that gets stored in tasks.input_payload
    input_payload: Dict[str, Any] = {
        "kind": "teacher_research",
        "question": payload.question,
        "max_sources": payload.max_sources,
        "domains_allow": payload.domains_allow,
        "include_snippets": payload.include_snippets,
        "task_type": "teacher",
        "priority": payload.priority,
        "origin": {
            "submitted_by": payload.submitted_by,
            "origin_type": "bobctl",
            "source_node": "orchestrator-server",
            "source_tool": "bobctl submit-teacher",
        },
    }

    # 2) Create DB task row
    db_task = create_task(
        high_level_type="teacher",
        input_payload=input_payload,
        submitted_by=payload.submitted_by,
        is_experiment=False,
        input_hash=None,
    )
    task_uuid = db_task["task_uuid"]

    logger.info("[TEACHER_TASK_CREATE] uuid=%s submitted_by=%s", task_uuid, payload.submitted_by)

    # 3) Mark RUNNING + create execution record
    try:
        update_task_status(task_uuid=task_uuid, final_status="RUNNING")
    except Exception as e:
        logger.exception("Failed to set teacher task RUNNING: %s", e)

    exec_row = create_task_execution(
        task_uuid=task_uuid,
        target_module="teacher_council",
        target_node=ORCHESTRATOR_NODE_NAME,
        strategy_name="teacher:default_v1",
    )
    execution_id = exec_row["id"]

    # 4) Execute Teacher Council call
    try:
        started = _utc_now()
        result = call_teacher(
            question=payload.question,
            max_sources=payload.max_sources,
            domains_allow=payload.domains_allow,
            include_snippets=payload.include_snippets,
        )
        ended = _utc_now()
        latency_ms = int((ended - started).total_seconds() * 1000)

        output_summary = result.get("summary", "").strip() or "Teacher Council completed."


        # 5) Complete execution + task status
        complete_task_execution(
            execution_id=execution_id,
            status="SUCCESS",
            output_summary=output_summary,
            error_type=None,
            latency_ms=latency_ms,
            metrics=result,  # full JSON goes into metrics_json
        )
        update_task_status(task_uuid=task_uuid, final_status="SUCCESS", error_type=None)

        # --- Memory Bob event logging (Teacher Council success) ---
        write_event({
            "task_id": task_uuid,
            "module": "teacher_council",
            "node_id": ORCHESTRATOR_NODE_NAME,
            "status": "success",
            "summary": output_summary,
            "details": {
                "sources": result.get("sources", []),
                "confidence": result.get("confidence"),
                "latency_ms": latency_ms,
            },
            "tags": ["teacher", "success"],
        })

        logger.info("[TEACHER_TASK_SUCCESS] uuid=%s exec_id=%s latency_ms=%s", task_uuid, execution_id, latency_ms)

        return {
            "status": "ok",
            "task_uuid": task_uuid,
            "execution_id": execution_id,
            "final_status": "SUCCESS",
            "summary": output_summary,
            "sources": result.get("sources", []),
            "confidence": result.get("confidence", None),
        }

    except Exception as e:
        err = str(e)
        logger.exception("[TEACHER_TASK_FAILED] uuid=%s exec_id=%s error=%s", task_uuid, execution_id, err)

        # best-effort DB updates
        try:
            complete_task_execution(
                execution_id=execution_id,
                status="FAILED",
                output_summary=err,
                error_type=err,
                latency_ms=None,
                metrics={"error": err},
            )
        except Exception:
            pass

        try:
            update_task_status(task_uuid=task_uuid, final_status="FAILED", error_type=err)
        except Exception:
            pass

        # --- Memory Bob event logging (Teacher Council failure) ---
        write_event({
            "task_id": task_uuid,
            "module": "teacher_council",
            "node_id": ORCHESTRATOR_NODE_NAME,
            "status": "failed",
            "summary": err,
            "details": {"error": err},
            "tags": ["teacher", "failed"],
        })

        raise HTTPException(status_code=500, detail=f"Teacher task failed: {err}")
