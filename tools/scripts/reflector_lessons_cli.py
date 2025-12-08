#!/usr/bin/env python
import os
import sys
import textwrap
import requests


def get_reflector_host() -> str:
    # Same pattern as show-reflector: separate service on 5081
    return os.environ.get("BOBIVERSE_REFLECTOR_HOST", "http://localhost:5081")


def print_lessons(base_url: str, limit: int = 10):
    url = f"{base_url}/reflector/lessons/recent"
    try:
        resp = requests.get(url, params={"limit": limit}, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Failed to reach Reflector lessons at {url}: {e}")
        sys.exit(1)

    lessons = resp.json()

    print("=== Bobiverse Reflector Lessons ===\n")

    if not lessons:
        print("No lessons recorded yet.\n")
        return

    for l in lessons:
        summary = textwrap.shorten(l["summary_text"], width=100, placeholder="…")
        tags = ", ".join(l.get("tags", [])) if l.get("tags") else "-"
        print(f"[{l['id']}] {l['created_at']}  ({l.get('source','?')})")
        print(f"  Tags   : {tags}")
        print(f"  Summary: {summary}")
        print()

    print(f"Total lessons shown: {len(lessons)}")


def main():
    base = get_reflector_host()
    print_lessons(base, limit=10)


def cli(args, orch_url=None):
    """
    Entry point for bobctl.
    orch_url is ignored; Reflector is on its own port.
    """
    base = get_reflector_host()
    # If your argparser supports a --limit later, you can read it from args
    print_lessons(base, limit=10)


if __name__ == "__main__":
    main()
