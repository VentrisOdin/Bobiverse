import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Literal
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from typing import Dict, List, Optional, Literal

from db.db_manager import (
    init_db,
    create_task_uuid,
    log_task,
    log_task_execution,
    update_task_final_status,
)

# Load .env if present
load_dotenv()

# Initialize database on startup
init_db()

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

# ---------- Data Models ---------- #

class NodeRegistration(BaseModel):
    name: str
    role: Literal["server", "worker"]
    tailscale_ip: str
    capabilities: List[str] = Field(default_factory=list)  # e.g. ["trading", "dev", "medical"]


class NodeHeartbeat(BaseModel):
    name: str
    load: Optional[float] = None           # 0.0–1.0 normalized CPU load
    free_memory_mb: Optional[int] = None
    active_councils: List[str] = Field(default_factory=list)


class NodeInfo(BaseModel):
    name: str
    role: str
    tailscale_ip: str
    capabilities: List[str] = Field(default_factory=list)
    last_seen: datetime
    load: Optional[float] = None
    free_memory_mb: Optional[int] = None
    active_councils: List[str] = Field(default_factory=list)


class NodeHealth(BaseModel):
    name: str
    status: Literal["online", "stale"]
    last_seen: datetime
    load: Optional[float] = None
    free_memory_mb: Optional[int] = None


# ---------- Task Models (Phase 1.5: in-memory only) ---------- #

class TaskSubmit(BaseModel):
    description: str
    target_node: Optional[str] = None  # if None, Prime Bob will pick a node


class TaskInfo(BaseModel):
    id: int
    description: str
    target_node: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    created_at: datetime
    updated_at: datetime
    result: Optional[str] = None


class TaskResult(BaseModel):
    node_name: str
    status: Literal["completed", "failed"]
    result: Optional[str] = None


# In-memory node registry (Phase 1: keep it simple)
NODE_REGISTRY: Dict[str, NodeInfo] = {}

TASKS: Dict[int, TaskInfo] = {}
TASK_COUNTER: int = 0

# Map in-memory task.id -> DB task_uuid
TASK_DB_UUIDS: Dict[int, str] = {}


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
    target_name: Optional[str] = payload.target_node

    if target_name is not None:
        if target_name not in NODE_REGISTRY:
            raise HTTPException(
                status_code=404,
                detail=f"Target node '{target_name}' not found.",
            )
    else:
        target_name = _choose_node_for_task()
        if target_name is None:
            raise HTTPException(
                status_code=503,
                detail="No nodes available to run tasks.",
            )

    TASK_COUNTER += 1
    now = _utc_now()
    task = TaskInfo(
        id=TASK_COUNTER,
        description=payload.description,
        target_node=target_name,
        status="pending",
        created_at=now,
        updated_at=now,
        result=None,
    )
    TASKS[task.id] = task

    # ---------- NEW: log into DB ----------
    try:
        task_uuid = create_task_uuid()
        db_task_id = log_task(
            task_uuid=task_uuid,
            high_level_type="generic",          # you can refine this later
            submitted_by="api",                 # or "Matt", or request user
            input_payload=payload.dict(),
            initial_status="pending",
        )
        TASK_DB_UUIDS[task.id] = task_uuid

        logger.info(
            "[TASK_SUBMIT_DB] id=%s uuid=%s db_id=%s",
            task.id,
            task_uuid,
            db_task_id,
        )
    except Exception as e:
        # We don't want DB errors to break the API in dev;
        # just log them for now.
        logger.exception("Failed to log task to DB: %s", e)

    logger.info(
        "[TASK_SUBMIT] id=%s target_node=%s desc=%s",
        task.id,
        task.target_node,
        task.description,
    )

    return task


@app.get("/tasks/next", response_model=Optional[TaskInfo])
def next_task(node_name: str):
    """
    Called by a node to fetch its next pending task.
    Marks the task as in_progress.
    Returns 200 with a TaskInfo if a task exists, or 204 if none.
    """
    if node_name not in NODE_REGISTRY:
        raise HTTPException(status_code=404, detail=f"Node '{node_name}' not registered.")

    # Find first pending task for this node
    for task in TASKS.values():
        if task.target_node == node_name and task.status == "pending":
            task.status = "in_progress"
            task.updated_at = _utc_now()
            logger.info("[TASK_ASSIGN] id=%s -> node=%s", task.id, node_name)
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

    # ---------- NEW: update DB final status ----------
    task_uuid = TASK_DB_UUIDS.get(task_id)
    if task_uuid:
        try:
            # Map node-style status to DB-style status
            final_status = "success" if payload.status == "completed" else payload.status

            update_task_final_status(
                task_uuid=task_uuid,
                final_status=final_status,
                final_result_summary=payload.result,
                error_message=None,
            )
            logger.info(
                "[TASK_RESULT_DB] id=%s uuid=%s final_status=%s",
                task_id,
                task_uuid,
                final_status,
            )
        except Exception as e:
            logger.exception("Failed to update task in DB: %s", e)

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


# ---------- Dev-only: local run ---------- #

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=ORCHESTRATOR_PORT,
        reload=True,
    )
