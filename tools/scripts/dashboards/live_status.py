import os
import time
import requests
import sqlite3
from pathlib import Path


def _clear():
    os.system("clear")


def _get_nodes(orch_url: str):
    try:
        r = requests.get(f"{orch_url}/nodes", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[live-status] Error fetching nodes: {e}")
        return []


def _get_db_path() -> Path:
    return Path.home() / "bobiverse" / "orchestrator" / "db" / "bobiverse.db"


def _get_tasks(limit: int = 10):
    db_path = _get_db_path()
    if not db_path.exists():
        return [], f"DB not found at {db_path}"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (limit,))
        rows = cur.fetchall()
    except sqlite3.OperationalError as e:
        conn.close()
        return [], f"DB query error: {e}"

    conn.close()
    return rows, None


def cli(args, orch_url: str) -> None:
    interval = args.interval

    try:
        while True:
            _clear()
            print("=== Bobiverse Live Status ===")
            print(f"Orchestrator: {orch_url}\n")

            # ---- Nodes ----
            nodes = _get_nodes(orch_url)
            print(f"Nodes ({len(nodes)}):")
            print(f"{'NAME':20} {'ROLE':10} {'LOAD':8} {'FREE_MB':8} {'LAST_SEEN':27} CAPABILITIES")
            print("-" * 100)
            for n in nodes:
                name = str(n.get("name", ""))
                role = str(n.get("role", ""))
                load = n.get("load", "")
                free_mb = n.get("free_memory_mb", "")
                last_seen = str(n.get("last_seen", ""))
                caps = n.get("capabilities", [])
                load_str = f"{load:.3f}" if isinstance(load, (int, float)) else str(load)
                caps_str = ", ".join(caps) if isinstance(caps, list) else str(caps)
                print(f"{name:20} {role:10} {load_str:8} {str(free_mb):8} {last_seen:27} {caps_str}")
            print()

            # ---- Tasks ----
            tasks, err = _get_tasks(limit=10)
            print("Recent tasks:")
            if err:
                print(f"[live-status] {err}")
            else:
                print(f"{'TASK':10} {'TYPE':12} {'STATUS':12} {'TIME':25} SUMMARY")
                print("-" * 100)

                if tasks:
                    cols = tasks[0].keys()
                else:
                    cols = []

                task_id_key = "task_uuid" if "task_uuid" in cols else ("id" if "id" in cols else None)
                type_key = "high_level_type" if "high_level_type" in cols else None
                status_key = (
                    "final_status"
                    if "final_status" in cols
                    else ("status" if "status" in cols else None)
                )

                ts_key = None
                for cand in ("created_at", "submitted_at", "created", "submitted"):
                    if cand in cols:
                        ts_key = cand
                        break

                summary_key = None
                for cand in ("input_summary", "description", "title"):
                    if cand in cols:
                        summary_key = cand
                        break

                for r in tasks:
                    tid = str(r[task_id_key]) if task_id_key else ""
                    ttype = str(r[type_key]) if type_key else ""
                    status = str(r[status_key]) if status_key else ""
                    ts = str(r[ts_key]) if ts_key else ""
                    summary = str(r[summary_key]) if summary_key else ""
                    if len(summary) > 50:
                        summary = summary[:47] + "..."
                    print(f"{tid[:10]:10} {ttype[:12]:12} {status[:12]:12} {ts[:25]:25} {summary}")

            print(f"\nRefreshing every {interval} seconds (Ctrl+C to exit)...")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[live-status] Exiting.")
