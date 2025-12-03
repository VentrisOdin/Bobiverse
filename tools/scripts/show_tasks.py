import sqlite3
from pathlib import Path


def _get_db_path() -> Path:
    # Same DB used by orchestrator
    return Path.home() / "bobiverse" / "orchestrator" / "db" / "bobiverse.db"


def cli(args, orch_url: str) -> None:  # orch_url unused, we go direct to DB
    db_path = _get_db_path()
    if not db_path.exists():
        print(f"[show-tasks] DB not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT ?", (args.limit,))
    except sqlite3.OperationalError as e:
        print(f"[show-tasks] Error querying tasks table: {e}")
        conn.close()
        return

    rows = cur.fetchall()
    conn.close()

    if not rows:
        print("[show-tasks] No tasks found.")
        return

    # Work with whatever schema you actually have
    cols = rows[0].keys()

    # Prefer nice columns if they exist
    task_id_key = "task_uuid" if "task_uuid" in cols else ("id" if "id" in cols else None)
    type_key = "high_level_type" if "high_level_type" in cols else None
    status_key = (
        "final_status"
        if "final_status" in cols
        else ("status" if "status" in cols else None)
    )

    ts_key = None
    for cand in ("created_at", "submitted_at", "created_ts", "submitted_ts", "created", "submitted"):
        if cand in cols:
            ts_key = cand
            break

    summary_key = None
    for cand in ("input_summary", "description", "title"):
        if cand in cols:
            summary_key = cand
            break

    # Header
    print(f"{'TASK':10} {'TYPE':12} {'STATUS':12} {'TIME':25} SUMMARY")
    print("-" * 90)

    for r in rows:
        tid = str(r[task_id_key]) if task_id_key else ""
        ttype = str(r[type_key]) if type_key else ""
        status = str(r[status_key]) if status_key else ""
        ts = str(r[ts_key]) if ts_key else ""
        summary = str(r[summary_key]) if summary_key else ""

        # Shorten summary for table output
        if len(summary) > 50:
            summary = summary[:47] + "..."

        print(f"{tid[:10]:10} {ttype[:12]:12} {status[:12]:12} {ts[:25]:25} {summary}")
