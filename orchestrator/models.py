# orchestrator/models.py

from datetime import datetime
from typing import Dict, Any, Optional, List, Literal

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
    # NEW: explicit task type for routing
    high_level_type: Optional[str] = "generic"  # e.g. "dev", "trading", "medical", "general"

    # Human-readable description (optional if everything is in input_payload)
    description: Optional[str] = None

    # Structured payload for specialist councils
    input_payload: Optional[Dict[str, Any]] = None

    # Who originated this task
    submitted_by: Optional[str] = "user"

    # If None, Prime Bob will auto-choose based on capabilities
    target_node: Optional[str] = None


class TaskInfo(BaseModel):
    id: int
    description: str
    target_node: str
    status: Literal["pending", "in_progress", "completed", "failed"]
    created_at: datetime
    updated_at: datetime
    result: Optional[str] = None

    # NEW: preserve type + payload for Reflector / councils
    high_level_type: Optional[str] = "generic"
    input_payload: Dict[str, Any] = Field(default_factory=dict)


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


# ---------- Policy Proposal Models ---------- #

class PolicyProposalCreate(BaseModel):
    source: str = "reflector"
    proposal_type: str  # e.g. "ROUTING_ADJUSTMENT", "PROMPT_UPDATE"
    scope: Optional[str] = None         # e.g. "node:test-node", "module:DEV-CODEGEN"
    payload: Dict[str, Any]            # structured details
    rationale: Optional[str] = None    # human-readable explanation


class PolicyProposalRecord(BaseModel):
    id: int
    proposal_uuid: str
    source: Optional[str] = None
    proposal_type: str
    scope: Optional[str] = None
    payload_json: str
    rationale: Optional[str] = None
    status: str
    created_at: str
    decided_at: Optional[str] = None
    applied_at: Optional[str] = None


# ---------- (Optional) Reflector Models (for later) ---------- #

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
