# orchestrator/db/db_manager.py

import os
import sqlite3
import uuid
import json
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "bobiverse.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


@contextmanager
def get_connection():
    """
    Context manager that opens a SQLite connection and closes it automatically.
    Uses Row factory so you can access columns by name.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """
    Initialize the database using schema.sql if it hasn't been created yet.
    Safe to call multiple times; schema uses IF NOT EXISTS.
    """
    if not os.path.exists(SCHEMA_PATH):
        raise FileNotFoundError(f"schema.sql not found at {SCHEMA_PATH}")

    with get_connection() as conn, open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()
        conn.executescript(schema_sql)


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


# =========================
# TASK-LEVEL OPERATIONS
# =========================

def create_task(
    high_level_type: Optional[str],
    input_payload: Dict[str, Any],
    submitted_by: Optional[str] = None,
    is_experiment: bool = False,
    input_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new task row. Returns the full task record as a dict.
    """
    task_uuid = str(uuid.uuid4())
    payload_str = json.dumps(input_payload, ensure_ascii=False)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO tasks (
                task_uuid,
                high_level_type,
                input_payload,
                input_hash,
                submitted_by,
                is_experiment,
                final_status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            (
                task_uuid,
                high_level_type,
                payload_str,
                input_hash,
                submitted_by,
                1 if is_experiment else 0,
                "PENDING",
            ),
        )
        task_id = cur.lastrowid
        cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        return _row_to_dict(row)


def update_task_status(
    task_uuid: str,
    final_status: str,
    error_type: Optional[str] = None,
    reward_score: Optional[float] = None,
) -> None:
    """
    Update the final_status (and optionally error_type / reward_score) of a task.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        updates = ["final_status = ?", "updated_at = datetime('now')"]
        params: List[Any] = [final_status]

        if error_type is not None:
            updates.append("error_type = ?")
            params.append(error_type)

        if reward_score is not None:
            updates.append("reward_score = ?")
            params.append(reward_score)

        params.append(task_uuid)

        sql = f"UPDATE tasks SET {', '.join(updates)} WHERE task_uuid = ?"
        cur.execute(sql, params)


def get_task_by_uuid(task_uuid: str) -> Optional[Dict[str, Any]]:
    """
    Load a single task by its UUID.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM tasks WHERE task_uuid = ?", (task_uuid,))
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def list_recent_tasks(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Return the most recent tasks (for quick dashboards / debugging).
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT * FROM tasks
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]


# =========================
# EXECUTION-LEVEL OPERATIONS
# =========================

def create_task_execution(
    task_uuid: str,
    target_module: Optional[str],
    target_node: Optional[str],
    strategy_name: Optional[str] = "default_v1",
) -> Dict[str, Any]:
    """
    Create a task_executions row for a given task UUID.
    Returns the created execution as a dict.
    """
    strategy_name = strategy_name or "default_v1"

    with get_connection() as conn:
        cur = conn.cursor()

        # Look up the internal task ID first
        cur.execute("SELECT id FROM tasks WHERE task_uuid = ?", (task_uuid,))
        task_row = cur.fetchone()
        if not task_row:
            raise ValueError(f"No task found for task_uuid={task_uuid}")

        task_id = task_row["id"]

        cur.execute(
            """
            INSERT INTO task_executions (
                task_id,
                target_module,
                strategy_name,
                target_node,
                status,
                started_at
            )
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                task_id,
                target_module,
                strategy_name,
                target_node,
                "RUNNING",
            ),
        )

        exec_id = cur.lastrowid
        cur.execute("SELECT * FROM task_executions WHERE id = ?", (exec_id,))
        row = cur.fetchone()
        return _row_to_dict(row)


def complete_task_execution(
    execution_id: int,
    status: str,
    output_summary: Optional[str] = None,
    error_type: Optional[str] = None,
    latency_ms: Optional[int] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Mark a task_executions row as completed, with results/metrics.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        updates = [
            "status = ?",
            "completed_at = datetime('now')",
        ]
        params: List[Any] = [status]

        if output_summary is not None:
            updates.append("output_summary = ?")
            params.append(output_summary)

        if error_type is not None:
            updates.append("error_type = ?")
            params.append(error_type)

        if latency_ms is not None:
            updates.append("latency_ms = ?")
            params.append(latency_ms)

        if metrics is not None:
            metrics_json = json.dumps(metrics, ensure_ascii=False)
            updates.append("metrics_json = ?")
            params.append(metrics_json)

        params.append(execution_id)

        sql = f"UPDATE task_executions SET {', '.join(updates)} WHERE id = ?"
        cur.execute(sql, params)


def get_executions_for_task(task_uuid: str) -> List[Dict[str, Any]]:
    """
    Return all executions for a given task UUID, newest first.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute("SELECT id FROM tasks WHERE task_uuid = ?", (task_uuid,))
        task_row = cur.fetchone()
        if not task_row:
            return []

        task_id = task_row["id"]

        cur.execute(
            """
            SELECT * FROM task_executions
            WHERE task_id = ?
            ORDER BY started_at DESC
            """,
            (task_id,),
        )
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]


def list_recent_executions(
    target_module: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    Return the most recent task_executions rows, optionally filtered by target_module.
    Joined with tasks so we also expose task_uuid and high_level_type.

    This is read-only and intended for Reflector / observability.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        base_sql = """
            SELECT
                te.*,
                t.task_uuid,
                t.high_level_type
            FROM task_executions AS te
            JOIN tasks AS t
              ON te.task_id = t.id
        """

        params: List[Any] = []

        if target_module:
            base_sql += " WHERE te.target_module = ?"
            params.append(target_module)

        base_sql += """
            ORDER BY datetime(te.started_at) DESC
            LIMIT ?
        """
        params.append(limit)

        cur.execute(base_sql, tuple(params))
        rows = cur.fetchall()

    results: List[Dict[str, Any]] = []
    for r in rows:
        d = _row_to_dict(r)
        # Decode metrics_json only for this helper; elsewhere it stays as stored.
        mj = d.get("metrics_json")
        if isinstance(mj, str) and mj:
            try:
                d["metrics_json"] = json.loads(mj)
            except Exception:
                # If it's corrupt, just leave it as the original string
                pass
        results.append(d)

    return results


# =========================
# POLICY PROPOSAL OPERATIONS
# =========================

def create_policy_proposal(
    source: str,
    proposal_type: str,
    payload: Dict[str, Any],
    scope: Optional[str] = None,
    rationale: Optional[str] = None,
    status: str = "PENDING",
) -> Dict[str, Any]:
    """
    Insert a new policy proposal into the DB and return the row as a dict.
    """
    proposal_uuid = str(uuid.uuid4())
    payload_json = json.dumps(payload, ensure_ascii=False)

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO policy_proposals (
                proposal_uuid, source, proposal_type, scope,
                payload_json, rationale, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_uuid,
                source,
                proposal_type,
                scope,
                payload_json,
                rationale,
                status,
            ),
        )
        proposal_id = cur.lastrowid

        cur.execute(
            "SELECT * FROM policy_proposals WHERE id = ?",
            (proposal_id,),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else {
            "id": proposal_id,
            "proposal_uuid": proposal_uuid,
        }


def update_policy_proposal_status(
    proposal_uuid: str,
    status: str,
    decided_at: Optional[str] = None,
    applied_at: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Update status (and optionally decided/applied timestamps) for a proposal.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        fields = ["status = ?"]
        params: List[Any] = [status]

        if decided_at is not None:
            fields.append("decided_at = ?")
            params.append(decided_at)
        if applied_at is not None:
            fields.append("applied_at = ?")
            params.append(applied_at)

        params.append(proposal_uuid)

        cur.execute(
            f"""
            UPDATE policy_proposals
            SET {", ".join(fields)}
            WHERE proposal_uuid = ?
            """,
            tuple(params),
        )

        cur.execute(
            "SELECT * FROM policy_proposals WHERE proposal_uuid = ?",
            (proposal_uuid,),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def get_policy_proposal_by_uuid(proposal_uuid: str) -> Optional[Dict[str, Any]]:
    """
    Load a single policy proposal by its UUID.
    """
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM policy_proposals WHERE proposal_uuid = ?",
            (proposal_uuid,),
        )
        row = cur.fetchone()
        return _row_to_dict(row) if row else None


def list_policy_proposals(
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """
    List recent policy proposals, optionally filtered by status.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        if status:
            cur.execute(
                """
                SELECT * FROM policy_proposals
                WHERE status = ?
                ORDER BY datetime(created_at) DESC
                LIMIT ?
                """,
                (status, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM policy_proposals
                ORDER BY datetime(created_at) DESC
                LIMIT ?
                """,
                (limit,),
            )

        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]
