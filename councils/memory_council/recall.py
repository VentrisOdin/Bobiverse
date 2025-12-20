from __future__ import annotations

import json
from typing import List, Optional

from .models import RecallRequest, RecallResponse, RecallSnippet
from .storage_sqlite import SQLiteStore


def recall_from_sqlite(store: SQLiteStore, req: RecallRequest) -> RecallResponse:
    rows = store.search_events_like(query=req.query, module=req.module, limit=max(req.limit, 5))

    snippets: List[RecallSnippet] = []
    guidance: List[str] = []

    for r in rows[: req.limit]:
        # Create a compact snippet
        refs = []
        if r["task_id"]:
            refs.append(f"task:{r['task_id']}")
        refs.append(f"event:{r['id']}")

        tags = []
        try:
            tags = json.loads(r["tags_json"] or "[]")
        except Exception:
            tags = []

        snippets.append(
            RecallSnippet(
                text=f"[{r['module']}/{r['status']}] {r['summary']}",
                tags=tags,
                confidence=0.55,
                refs=refs,
            )
        )

    # v1 guidance rules: lightweight + deterministic
    if any("failed" == (s.text.split("]")[0].split("/")[-1] if "/" in s.text else "") for s in snippets):
        guidance.append("Review the most recent failures for this query before attempting changes.")
    if len(snippets) == 0:
        guidance.append("No prior memory found. Proceed normally and record the outcome.")

    return RecallResponse(snippets=snippets, guidance=guidance)
