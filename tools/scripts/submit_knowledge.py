import json
from typing import Any, Dict

import requests
import argparse


def cli(args: argparse.Namespace, orch_url: str) -> None:
    """
    Submit a Knowledge Council (knowledge_council) task via /submit_task.

    This mirrors submit-dev but for Knowledge Bob:
    - high_level_type = "knowledge"
    - target_module = "knowledge_council"
    - target_node = "data-mainpc"  (adjust if you move Knowledge Bob)
    """
    description: str = args.description
    details: str | None = getattr(args, "details", None)

    payload: Dict[str, Any] = {
        "high_level_type": "knowledge",
        "submitted_by": "bobctl",
        "target_module": "knowledge_council",
        "target_node": "data-mainpc",  # update if Knowledge Bob lives elsewhere
        "input_payload": {
            "task_type": "qa",
            "question": description,
            "details": details,
        },
    }

    # Strip None fields from input_payload
    payload["input_payload"] = {
        k: v for k, v in payload["input_payload"].items() if v is not None
    }

    url = f"{orch_url.rstrip('/')}/submit_task"
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"[knowledge] ERROR submitting task: {e}")
        return

    data = resp.json()
    task_id = data.get("id") or data.get("task_id") or data.get("task_uuid")

    print("[knowledge] Submitted task to knowledge_council")
    print(f"  Description : {description}")
    if details:
        print(f"  Details     : {details}")
    print(f"  ID / UUID   : {task_id}")
    print(f"  Status      : {data.get('status', 'unknown')}")
