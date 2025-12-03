import sqlite3
from pathlib import Path

def _get_db():
    return Path.home() / "bobiverse" / "orchestrator" / "db" / "bobiverse.db"

def _print_rows(cur, table, limit):
    print(f"\n=== {table} (last {limit}) ===")
    try:
        cur.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?", (limit,))
    except sqlite3.OperationalError as e:
        print(f"[db-inspect] Error querying {table}: {e}")
        return

    rows = cur.fetchall()
    if not rows:
        print("  (no rows)")
        return

    cols = rows[0].keys()
    print("  " + " | ".join(cols))
    print("  " + "-" * 80)
    for r in rows:
        print("  " + " | ".join(str(r[c]) for c in cols))

def cli(args, orch_url):
    db_path = _get_db()
    if not db_path.exists():
        print(f"[db-inspect] DB not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    _print_rows(cur, "tasks", args.limit)
    _print_rows(cur, "task_executions", args.limit)

    conn.close()
