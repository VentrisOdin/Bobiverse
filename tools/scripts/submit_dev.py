import requests
import json
import os
from pathlib import Path

def cli(args, orch_url):
    details = None
    if args.details:
        p = Path(args.details)
        details = p.read_text() if p.exists() else args.details

    payload = {
        "high_level_type": "dev",
        "submitted_by": "prime_bob",
        "target_module": "dev_council",
        "priority": "normal",
        "input_payload": {
            "description": args.description,
            "details": details
        }
    }

    url = f"{orch_url}/tasks"
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[submit-dev] Error: {e}")
        return

    print(json.dumps(r.json(), indent=2))
