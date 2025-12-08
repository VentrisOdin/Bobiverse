#!/usr/bin/env python
import os
import sys
import textwrap
import requests


def fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


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
        # naive but effective: swap :5080 -> :5081 if present
        if ":5080" in orch_url:
            return orch_url.replace(":5080", ":5081")
        # otherwise just assume same host but on 5081
        return orch_url.rsplit(":", 1)[0] + ":5081"

    return "http://localhost:5081"


def show_reflector(reflector_host: str):
    url = f"{reflector_host}/reflector/insights"
    try:
        resp = requests.get(url, params={"limit_failures": 10}, timeout=5)
        resp.raise_for_status()
    except Exception as e:
        print(f"[ERROR] Failed to reach Reflector at {url}: {e}")
        sys.exit(1)

    data = resp.json()

    summary = data["summary"]
    worst_nodes = data["worst_nodes"]
    worst_modules = data["worst_modules"]
    top_error_types = data["top_error_types"]
    recent_failures = data["recent_failures"]

    print("=== Bobiverse Reflector v1 ===\n")

    # --- Summary ---
    print("Summary")
    print("-------")
    print(f"Total tasks    : {summary['total_tasks']}")
    print(f"Success        : {summary['success_count']}")
    print(f"Failed         : {summary['failed_count']}")
    print(f"Success rate   : {fmt_pct(summary['success_rate'])}")
    print()

    # --- Nodes ---
    print("Node Error Rates")
    print("----------------")
    if not worst_nodes:
        print("No node executions recorded yet.\n")
    else:
        print(f"{'Node':15} {'Execs':>7} {'Failed':>7} {'Fail%':>7}")
        print("-" * 40)
        for n in worst_nodes:
            print(
                f"{n['node_name']:15} "
                f"{n['total_executions']:7d} "
                f"{n['failed_executions']:7d} "
                f"{fmt_pct(n['failed_rate']):>7}"
            )
        print()

    # --- Modules ---
    print("Module Error Rates")
    print("------------------")
    if not worst_modules:
        print("No module executions recorded yet.\n")
    else:
        print(f"{'Module':15} {'Execs':>7} {'Failed':>7} {'Fail%':>7}")
        print("-" * 40)
        for m in worst_modules:
            print(
                f"{m['module_name']:15} "
                f"{m['total_executions']:7d} "
                f"{m['failed_executions']:7d} "
                f"{fmt_pct(m['failed_rate']):>7}"
            )
        print()

    # --- Error types ---
    print("Top Error Types")
    print("---------------")
    if not top_error_types:
        print("No failed tasks recorded yet.\n")
    else:
        for e in top_error_types:
            etype = e["error_type"] or "<None>"
            count = e["count"]
            last_seen = e["last_seen"]
            short = textwrap.shorten(etype, width=100, placeholder="…")
            print(f"- {count:3d} ×  {short}")
            print(f"    last_seen: {last_seen}")
        print()

    # --- Recent failures ---
    print("Recent Failed Tasks")
    print("-------------------")
    if not recent_failures:
        print("No recent failures.\n")
    else:
        for f in recent_failures:
            print(
                f"- {f['created_at']} | {f['task_uuid']} | "
                f"type={f['high_level_type']} | status={f['final_status']}"
            )
            if f["error_type"]:
                short_err = textwrap.shorten(f["error_type"], width=120, placeholder="…")
                print(f"    error: {short_err}")
        print()


def main():
    base = os.environ.get("BOBIVERSE_REFLECTOR_HOST", "http://localhost:5081")
    show_reflector(base)


def cli(args, orch_url=None):
    """
    Entry point for bobctl.
    'orch_url' is ignored because the Reflector is a separate service.
    """
    base = os.environ.get("BOBIVERSE_REFLECTOR_HOST", "http://localhost:5081")
    show_reflector(base)


if __name__ == "__main__":
    main()
