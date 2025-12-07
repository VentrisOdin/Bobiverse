import requests
import json
from pathlib import Path


def _load_details(details_arg: str | None) -> str | None:
    if not details_arg:
        return None
    p = Path(details_arg)
    if p.exists() and p.is_file():
        return p.read_text()
    return details_arg  # treat as raw text


def cli(args, orch_url: str) -> None:
    description = args.description
    details = _load_details(args.details)

    payload = {
        "description": description,
        "details": details,
        "submitted_by": "bobctl",
        "priority": "normal",
    }

    url = f"{orch_url}/tasks/dev"
    print(f"[submit-dev] POST {url}")
    print(f"[submit-dev] Payload: {json.dumps(payload, indent=2)}")

    try:
        resp = requests.post(url, json=payload, timeout=10)
        print(f"[submit-dev] HTTP {resp.status_code}")
        resp.raise_for_status()
    except requests.HTTPError as e:
        print(f"[submit-dev] HTTP error from {url}: {e} ({e.response.status_code})")
        try:
            print("Response:", e.response.text)
        except Exception:
            pass
        return
    except Exception as e:
        print(f"[submit-dev] Error submitting task to {url}: {e}")
        return

    try:
        data = resp.json()
    except Exception:
        print("[submit-dev] Non-JSON response:")
        print(resp.text)
        return

    print("[submit-dev] Created dev task:")
    print(json.dumps(data, indent=2))
