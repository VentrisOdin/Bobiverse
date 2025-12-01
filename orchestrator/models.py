# orchestrator/models.py

from datetime import datetime
from typing import Dict, List, Optional, Literal, Any

from pydantic import BaseModel, Field


# ---------- Node Models ---------- #

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


# ---------- Task Models (in-memory tasks) ---------- #

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


# ---------- DB Task Models (Phase 1.6) ---------- #

class DbTaskCreate(BaseModel):
    input_payload: Dict[str, Any]
    high_level_type: Optional[str] = "generic"
    submitted_by: Optional[str] = "api"
    is_experiment: bool = False
    input_hash: Optional[str] = None


# ---------- (Optional) Reflector Models (for later) ---------- #
# These are stubs we can flesh out when we build Reflector v0.

class ReflectorTaskStats(BaseModel):
    total_tasks: int
    success_count: int
    failed_count: int
    success_rate: float


class ReflectorNodeErrorStats(BaseModel):
    node_name: str
    total_executions: int
    failed_executions: int
    failed_rate: float
