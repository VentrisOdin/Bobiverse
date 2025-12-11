#!/usr/bin/env python
import os
import sys
import json
import requests


def resolve_reflector_host(orch_url: str | None) -> str:
    """
    Decide which base URL to use for the Reflector.

    Priority:
    1. BOBIVERSE_REFLECTOR_HOST env var
    2. orch_url with port swapped to 5081 (if provided)
    3. http://localhost:5081 as a fallback
    """
    env_host = os.environ.get("BOBIVERSE_REFLECTOR_HOST")
    if env_host:
        return env_host

    if orch_url:
        if ":5080" in orch_url:
            return orch_url.replace(":5080", ":5081")
        # crude but fine: nuke any trailing :port and add :5081
        if "://" in orch_url:
            base = orch_url.split("://", 1)[1]
            if ":" in base:
                host = base.split(":", 1)[0]
            else:
                host = base
            scheme = orch_url.split("://", 1)[0]
            return f"{scheme}://{host}:5081"
    return "http://localhost:5081"


def cli(args, orch_url=None) -> None:
    """
    bobctl reflector-run entry point.

    Calls POST {reflector_host}/reflector/run with JSON:
      { "module": <optional>, "limit": <int> }
    and prints a human-friendly summary.
    """
    reflector_host = resolve_reflector_host(orch_url)
    url = f"{reflector_host.rstrip('/')}/reflector/run"

    payload = {
        "module": args.module,
        "limit": args.limit,
    }

    try:
        resp = requests.post(url, json=payload, timeout=120)
    except Exception as e:
        print(f"[reflector-run] Failed to reach Reflector at {url}: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code != 200:
        print(
            f"[reflector-run] Reflector returned {resp.status_code}: {resp.text}",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        data = resp.json()
    except json.JSONDecodeError:
        print("[reflector-run] Non-JSON response from Reflector:")
        print(resp.text)
        return

    # Expected shape (we will wire the service to match):
    # {
    #   "status": "ok",
    #   "module": "dev_council" | null,
    #   "limit": 200,
    #   "execution_id": 123,
    #   "summary": "Short description of what the Reflector did",
    #   "lessons_created": 3,
    #   "proposals_created": 1,
    # }
    print("=== Reflector Run ===")
    print(f"Status  : {data.get('status', 'UNKNOWN')}")
    if "module" in data:
        print(f"Module  : {data['module'] or '<all>'}")
    if "limit" in data:
        print(f"Scope   : last {data['limit']} executions")

    if "execution_id" in data:
        print(f"Exec ID : {data['execution_id']}")
    if "task_uuid" in data:
        print(f"Task ID : {data['task_uuid']}")

    lessons = data.get("lessons_created")
    proposals = data.get("proposals_created")
    if lessons is not None or proposals is not None:
        print("\nArtifacts:")
        if lessons is not None:
            print(f"  Lessons   : {lessons}")
        if proposals is not None:
            print(f"  Proposals : {proposals}")

    if data.get("summary"):
        print("\nSummary:")
        print(f"  {data['summary']}")
