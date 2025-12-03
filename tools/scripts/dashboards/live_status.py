import os
import time
import requests

def _clear():
    os.system("clear")

def _get_nodes(orch_url):
    try:
        r = requests.get(f"{orch_url}/nodes", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[live-status] Error fetching nodes: {e}")
        return []

def _get_tasks(orch_url, limit=10):
    try:
        r = requests.get(f"{orch_url}/tasks/recent?limit={limit}", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[live-status] Error fetching tasks: {e}")
        return []

def cli(args, orch_url):
    interval = args.interval

    while True:
        _clear()
        print("=== Bobiverse Live Status ===")
        print(f"Orchestrator: {orch_url}\n")

        nodes = _get_nodes(orch_url)
        print(f"Nodes ({len(nodes)}):")
        print(f"{'NAME':20} {'ROLE':10} {'STATUS':10} LAST_HEARTBEAT")
        print("-" * 70)
        for n in nodes:
            name = n.get("node_name", "?")
            role = n.get("role", "?")
            status = n.get("status", "?")
            last = n.get("last_heartbeat") or n.get("last_seen") or "?"
            print(f"{name:20} {role:10} {status:10} {last}")
        print()

        tasks = _get_tasks(orch_url, limit=10)
        print("Recent tasks:")
        print(f"{'ID':10} {'TYPE':10} {'STATUS':12} SUBMITTED")
        print("-" * 70)
        for t in tasks:
            tid = (t.get("task_uuid") or t.get("id") or "?")[:10]
            hl = (t.get("high_level_type") or "?")[:10]
            status = (t.get("final_status") or t.get("status") or "?")[:12]
            submitted = t.get("submitted_at") or t.get("created_at") or "?"
            print(f"{tid:10} {hl:10} {status:12} {submitted}")

        print(f"\nRefreshing every {interval} seconds (Ctrl+C to exit)...")
        time.sleep(interval)
