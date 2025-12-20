from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


Status = Literal["success", "failed", "partial", "running", "unknown"]


class HealthResponse(BaseModel):
    status: str = "ok"
    council: str = "memory_council"
    storage: str = "sqlite"
    qdrant_enabled: bool = False
    qdrant_ok: bool = False
    timestamp_utc: str


class MemoryEventIn(BaseModel):
    task_id: Optional[str] = Field(default=None, description="Orchestrator task id (uuid or string)")
    module: str = Field(..., description="Which council/module produced this event (dev_council, ops_bob, etc.)")
    node_id: Optional[str] = Field(default=None, description="Which node executed the task")
    status: Status = Field(default="unknown")
    summary: str = Field(..., description="Short human-readable summary")
    details: Dict[str, Any] = Field(default_factory=dict, description="Structured details, error, fix, etc.")
    tags: List[str] = Field(default_factory=list)
    artifacts: Dict[str, Any] = Field(default_factory=dict)

    created_at_utc: Optional[str] = Field(
        default=None,
        description="If omitted, server sets it. ISO8601 UTC string.",
    )


class MemoryEventOut(BaseModel):
    event_id: int
    created_at_utc: str


class RecallRequest(BaseModel):
    query: str
    module: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    limit: int = 5


class RecallSnippet(BaseModel):
    text: str
    tags: List[str] = Field(default_factory=list)
    confidence: float = 0.5
    refs: List[str] = Field(default_factory=list)


class RecallResponse(BaseModel):
    snippets: List[RecallSnippet] = Field(default_factory=list)
    guidance: List[str] = Field(default_factory=list)


class DistillRequest(BaseModel):
    lookback: int = Field(default=200, description="How many recent events to consider")
    min_repeats: int = Field(default=2, description="Minimum repeats to promote a lesson")
    limit_new_lessons: int = Field(default=10, description="Max new lessons to create in one run")


class DistilledLesson(BaseModel):
    lesson_id: int
    title: str
    text: str
    tags: List[str] = Field(default_factory=list)
    refs: List[str] = Field(default_factory=list)
    created_at_utc: str


class DistillResponse(BaseModel):
    created: int
    lessons: List[DistilledLesson] = Field(default_factory=list)
