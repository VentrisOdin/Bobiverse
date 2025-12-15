import argparse
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


def _get_db_path() -> Path:
    """
    Locate the bobiverse.db file relative to the repo root.

    Assumes this script lives in:
      bobiverse/tools/scripts/show_knowledge.py

    DB is at:
      bobiverse/orchestrator/db/bobiverse.db
    """
    tools_dir = Path(__file__).resolve().parents[1]  # .../bobiverse/tools
    db_path = tools_dir.parent / "orchestrator" / "db" / "bobiverse.db"
    return db_path


def _fetch_knowledge_executions(limit: int) -> List[Dict[str, Any]]:
    """
    Read recent Knowledge Council executions directly from SQLite.
    Mirrors the style of db_inspect.
    """
    db_path = _get_db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found at {db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        # Only knowledge_council executions, newest first
        cur.execute(
            """
            SELECT
                id,
                task_id,
                target_module,
                target_node,
                strategy_name,
                status,
                output_summary,
                output_hash,
                error_type,
                latency_ms,
                metrics_json,
                started_at,
                completed_at
            FROM task_executions
            WHERE target_module = 'knowledge_council'
            ORDER BY completed_at DESC, started_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append({k: row[k] for k in row.keys()})
        return result
    finally:
        conn.close()


def cli(args: argparse.Namespace, orch_url: str) -> None:  # orch_url unused here
    """
    Show recent Knowledge Council executions by reading bobiverse.db directly.
    """
    limit: int = getattr(args, "limit", 20)

    try:
        rows = _fetch_knowledge_executions(limit)
    except Exception as e:
        print(f"[knowledge] ERROR reading DB: {e}")
        return

    if not rows:
        print("No recent Knowledge Council executions found.")
        return

    print(f"=== Last {len(rows)} Knowledge Council executions ===")
    for r in rows:
        rid = r.get("id")
        status = r.get("status")
        started = r.get("started_at")
        completed = r.get("completed_at")
        summary = r.get("output_summary") or ""

        # Try to pull a nicer answer from metrics_json.analysis if present
        answer: Optional[str] = None
        reasoning: Optional[str] = None
        metrics_json = r.get("metrics_json")
        if isinstance(metrics_json, str):
            # metrics_json is stored as JSON text; we can parse lazily
            import json

            try:
                mj = json.loads(metrics_json)
                analysis = mj.get("analysis", {})
                if isinstance(analysis, dict):
                    answer = analysis.get("answer") or answer
                    reasoning = analysis.get("reasoning") or reasoning
            except Exception:
                pass

        print("-" * 60)
        print(f"ID        : {rid}")
        print(f"Status    : {status}")
        print(f"Started   : {started}")
        print(f"Completed : {completed}")

        if answer:
            print(f"Answer    : {answer}")
        else:
            print(f"Summary   : {summary}")

        if reasoning:
            short_reason = reasoning
            if len(short_reason) > 240:
                short_reason = short_reason[:237] + "..."
            print(f"Reasoning : {short_reason}")

    print("-" * 60)
