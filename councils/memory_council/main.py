from __future__ import annotations

import logging

from fastapi import FastAPI

from . import config
from .models import (
    DistillRequest,
    DistillResponse,
    HealthResponse,
    MemoryEventIn,
    MemoryEventOut,
    RecallRequest,
    RecallResponse,
)
from .qdrant_store import QdrantStore
from .recall import recall_from_sqlite
from .storage_sqlite import SQLiteStore
from .utils import utc_now_iso

logger = logging.getLogger("memory_council")
logger.setLevel(logging.INFO)

app = FastAPI(
    title="Memory Bob Council v1",
    description="Canonical memory capture + recall + distillation for Bobiverse",
    version="1.0.0",
)

store = SQLiteStore(config.CANONICAL_DB_PATH)
qdrant = QdrantStore(config.QDRANT_HOST, config.QDRANT_PORT, timeout=getattr(config, "MEMORY_QDRANT_TIMEOUT", 5))


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    q_ok = qdrant.health()
    return HealthResponse(
        qdrant_enabled=qdrant.enabled,
        qdrant_ok=q_ok,
        timestamp_utc=utc_now_iso(),
    )


@app.post("/memory/event", response_model=MemoryEventOut)
def write_event(ev: MemoryEventIn) -> MemoryEventOut:
    created = ev.created_at_utc or utc_now_iso()
    event_id = store.insert_event(
        created_at_utc=created,
        task_id=ev.task_id,
        module=ev.module,
        node_id=ev.node_id,
        status=ev.status,
        summary=ev.summary,
        details=ev.details,
        tags=ev.tags,
        artifacts=ev.artifacts,
    )
    return MemoryEventOut(event_id=event_id, created_at_utc=created)


@app.post("/memory/recall", response_model=RecallResponse)
def recall(req: RecallRequest) -> RecallResponse:
    # v1: SQLite recall only (works immediately). Qdrant recall comes later with embeddings.
    return recall_from_sqlite(store, req)


@app.post("/memory/distill", response_model=DistillResponse)
def distill(req: DistillRequest) -> DistillResponse:
    from .distill import distill_lessons

    return distill_lessons(store, req)
