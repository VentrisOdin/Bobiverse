import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

from db.db_manager import (
    init_db,
    create_task,
    get_task_by_uuid,
    update_task_status,
    create_task_execution,
    complete_task_execution,
    get_executions_for_task,
    list_recent_tasks,
    create_policy_proposal,
    list_policy_proposals,
    get_policy_proposal_by_uuid,
    update_policy_proposal_status,
)
from models import (
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

    # Filter to nodes with a load value
    nodes_with_load = [n for n in NODE_REGISTRY.values() if n.load is not None]

    if nodes_with_load:
        chosen = min(nodes_with_load, key=lambda n: n.load)
    else:
        # Fall back to first node if no load info
        chosen = sorted(NODE_REGISTRY.values(), key=lambda n: n.name.lower())[0]

    return chosen.name


def choose_node_for_capability(task_type: str) -> Optional[str]:
    """
    Return a node that advertises capability matching the high_level_type.
    E.g. task_type='dev' => node with 'dev' in node.capabilities.

    If none match, fall back to lowest-load node.
    """
    if not NODE_REGISTRY:
        return None

    # Filter by capability
    capable_nodes = [
        n for n in NODE_REGISTRY.values()
        if task_type in n.capabilities
    ]

    if capable_nodes:
        # Pick lowest load among capable nodes
        nodes_with_load = [n for n in capable_nodes if n.load is not None]
        if nodes_with_load:
            chosen = min(nodes_with_load, key=lambda n: n.load)
        else:
            chosen = sorted(capable_nodes, key=lambda n: n.name.lower())[0]
        return chosen.name

    # Fallback: use generic lowest-load selector
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
                        strategy_name=None,
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


# ---------- Dev-only: local run ---------- #

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=ORCHESTRATOR_PORT,
        reload=True,
    )
