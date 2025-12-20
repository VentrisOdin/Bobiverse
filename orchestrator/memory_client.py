import os
import requests
from typing import Any, Dict, Optional

MEMORY_URL = os.getenv("MEMORY_COUNCIL_URL", "").rstrip("/")

def memory_enabled() -> bool:
    return bool(MEMORY_URL)

def write_event(payload: Dict[str, Any]) -> None:
    if not memory_enabled():
        return
    try:
        requests.post(f"{MEMORY_URL}/memory/event", json=payload, timeout=3)
    except Exception:
        # fail-open: memory must never break task flow
        return

def recall(query: str, module: Optional[str] = None, limit: int = 5) -> Optional[Dict[str, Any]]:
    if not memory_enabled():
        return None
    body: Dict[str, Any] = {"query": query, "limit": limit}
    if module:
        body["module"] = module
    try:
        r = requests.post(f"{MEMORY_URL}/memory/recall", json=body, timeout=3)
        if r.status_code == 200:
            return r.json()
    except Exception:
        return None
    return None
