import requests
import json

def cli(args, orch_url):
    payload = {
        "high_level_type": "ops_shell",
        "submitted_by": "prime_bob",
        "target_module": "dev_council",
        "priority": "high",
        "target_node": args.target_node,
        "input_payload": {
            "command": args.command
        }
    }

    url = f"{orch_url}/tasks"
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"[submit-shell] Error: {e}")
        return

    print(json.dumps(r.json(), indent=2))
