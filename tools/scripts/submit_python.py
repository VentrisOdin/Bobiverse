import requests
import json
from pathlib import Path

def cli(args, orch_url):
    p = Path(args.file_or_code)
    code = p.read_text() if p.exists() else args.file_or_code

    payload = {
        "high_level_type": "python_exec",
        "submitted_by": "prime_bob",
        "target_module": "dev_council",
        "priority": "normal",
        "target_node": args.target_node,
        "input_payload": {
            "code": code
        }
    }

    url = f"{orch_url}/tasks"
    try:
        r = requests.post(url, json=payload, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"[submit-python] Error: {e}")
        return

    print(json.dumps(r.json(), indent=2))
