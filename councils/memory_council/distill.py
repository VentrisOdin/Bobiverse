from __future__ import annotations

import json
from collections import defaultdict
from typing import Dict, List, Tuple

from .models import DistillRequest, DistillResponse, DistilledLesson
from .storage_sqlite import SQLiteStore
from .utils import stable_hash, utc_now_iso


def _event_signature(row) -> str:
    # v1 signature: module + status + first tag + summary prefix
    try:
        tags = json.loads(row["tags_json"] or "[]")
    except Exception:
        tags = []
    t0 = tags[0] if tags else "no_tag"
    summary = (row["summary"] or "")[:80]
    raw = f"{row['module']}|{row['status']}|{t0}|{summary}"
    return stable_hash(raw)


def distill_lessons(store: SQLiteStore, req: DistillRequest) -> DistillResponse:
    events = store.get_recent_events(limit=req.lookback)

    buckets: Dict[str, List] = defaultdict(list)
    for e in events:
        sig = _event_signature(e)
        buckets[sig].append(e)

    created_lessons: List[DistilledLesson] = []

    # sort buckets by size desc
    for sig, rows in sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True):
        if len(created_lessons) >= req.limit_new_lessons:
            break
        if len(rows) < req.min_repeats:
            continue

        # Prefer failures/partials for lessons
        statuses = [r["status"] for r in rows]
        if not any(s in ("failed", "partial") for s in statuses):
            continue

        sample = rows[0]
        try:
            tags = json.loads(sample["tags_json"] or "[]")
        except Exception:
            tags = []

        title = f"{sample['module']}: recurring {sample['status']} pattern"
        text = (
            f"Repeated pattern detected ({len(rows)}x): {sample['summary']}\n"
            f"Action: investigate root cause and apply a stable fix; record the resolution as an event."
        )

        refs = []
        for r in rows[:10]:
            if r["task_id"]:
                refs.append(f"task:{r['task_id']}")
            refs.append(f"event:{r['id']}")

        lesson_id = store.insert_lesson_if_new(
            title=title,
            text=text,
            tags=tags,
            refs=refs,
            signature=sig,
            created_at_utc=utc_now_iso(),
        )

        if lesson_id is not None:
            created_lessons.append(
                DistilledLesson(
                    lesson_id=lesson_id,
                    title=title,
                    text=text,
                    tags=tags,
                    refs=refs,
                    created_at_utc=utc_now_iso(),
                )
            )

    return DistillResponse(created=len(created_lessons), lessons=created_lessons)
