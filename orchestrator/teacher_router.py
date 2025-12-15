import os
import requests
from typing import Dict, Any, Optional, List

TEACHER_URL = os.getenv("TEACHER_COUNCIL_URL", "http://127.0.0.1:8013").rstrip("/")

def call_teacher(
    question: str,
    max_sources: int = 6,
    domains_allow: Optional[List[str]] = None,
    include_snippets: bool = True,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "question": question,
        "max_sources": max_sources,
        "include_snippets": include_snippets,
    }
    if domains_allow is not None:
        payload["domains_allow"] = domains_allow

    r = requests.post(
        f"{TEACHER_URL}/teacher_council/research",
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()
