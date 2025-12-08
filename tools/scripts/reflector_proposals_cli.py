#!/usr/bin/env python
import os
import sys
import textwrap
import requests


def get_reflector_host() -> str:
    return os.environ.get("BOBIVERSE_REFLECTOR_HOST", "http://localhost:5081")


def print_proposals(base_url: str, limit: int = 10):
    url = f"{base_url}/reflector/proposals/recent"
    try:
        resp = requests.get(url, params={"limit": limit}, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Failed to reach Reflector proposals at {url}: {e}")
        sys.exit(1)

    proposals = resp.json()

    print("=== Bobiverse Reflector Proposals ===\n")

    if not proposals:
        print("No proposals recorded yet.\n")
        return

    for p in proposals:
        summary = textwrap.shorten(p["description"], width=100, placeholder="…")
        print(f"[{p['id']}] {p['created_at']}  ({p.get('source','?')})")
        print(f"  UUID    : {p['proposal_uuid']}")
        print(f"  Type    : {p['proposal_type']}")
        print(f"  Module  : {p['target_module']}")
        print(f"  Risk    : {p['risk_score']}")
        print(f"  Status  : {p['status']}")
        print(f"  Summary : {summary}")
        print()

    print(f"Total proposals shown: {len(proposals)}")


def main():
    base = get_reflector_host()
    print_proposals(base, limit=10)


def cli(args, orch_url=None):
    """
    Entry point for bobctl.
    orch_url is ignored; Reflector is on its own port.
    """
    base = get_reflector_host()
    print_proposals(base, limit=10)


if __name__ == "__main__":
    main()
