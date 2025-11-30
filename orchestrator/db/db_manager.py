# orchestrator/db/db_manager.py

import os
import sqlite3
from typing import Optional, Dict, Any, List
import json
import uuid
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

    # Ensure DB file exists and run schema
    with get_connection() as conn, open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()
        conn.executescript(schema_sql)


# ============
# Task helpers
# ============

def create_task_uuid() -> str:
    """Generate a new task UUID string."""
    return str(uuid.uuid4())


def log_task(
    task_uuid: str,
    high_level_type: Optional[str] = None,
    submitted_by: Optional[str] = None,
    input_payload: Optional[Dict[str, Any]] = None,
    initial_status: str = "pending",
) -> int:
    """
    Insert a new high-level task row.

    Returns:
        task_id (int): the auto-incremented primary key.
    """
    input_payload_json = json.dumps(input_payload) if input_payload is not None else None

    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks (
                task_uuid,
                high_level_type,
                submitted_by,
                input_payload,
                final_status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (task_uuid, high_level_type, submitted_by, input_payload_json, initial_status),
        )
        return cur.lastrowid


def update_task_final_status(
    task_uuid: str,
    final_status: str,
    final_result_summary: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    Mark a task as completed/failed/etc and set a final summary + error if needed.
    Also updates completed_at to NOW.
    """
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE tasks
            SET final_status = ?,
                final_result_summary = ?,
                error_message = ?,
                completed_at = CURRENT_TIMESTAMP
            WHERE task_uuid = ?
            """,
            (final_status, final_result_summary, error_message, task_uuid),
        )


def get_task_by_uuid(task_uuid: str) -> Optional[sqlite3.Row]:
    """
    Fetch a single task row by its task_uuid.
    Returns sqlite3.Row or None.
    """
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM tasks WHERE task_uuid = ?",
            (task_uuid,),
        )
        row = cur.fetchone()
        return row


# ======================
# Task executions helpers
# ======================

def log_task_execution(
    task_id: int,
    step_index: int,
    target_module: Optional[str] = None,
    target_node: Optional[str] = None,
    agent_name: Optional[str] = None,
    status: str = "running",
    metrics: Optional[Dict[str, Any]] = None,
    output_summary: Optional[str] = None,
    error_message: Optional[str] = None,
) -> int:
    """
    Insert a new execution step for a given task.

    Returns:
        execution_id (int): the auto-incremented primary key for this step.
    """
    metrics_json = json.dumps(metrics) if metrics is not None else None

    with get_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO task_executions (
                task_id,
                step_index,
                target_module,
                target_node,
                agent_name,
                status,
                metrics_json,
                output_summary,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                step_index,
                target_module,
                target_node,
                agent_name,
                status,
                metrics_json,
                output_summary,
                error_message,
            ),
        )
        return cur.lastrowid


def update_task_execution_status(
    execution_id: int,
    status: str,
    metrics: Optional[Dict[str, Any]] = None,
    output_summary: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """
    Update an existing execution step when it finishes.
    Sets finished_at to NOW and updates status/metrics/output/error.
    """
    metrics_json = json.dumps(metrics) if metrics is not None else None

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE task_executions
            SET status = ?,
                metrics_json = ?,
                output_summary = ?,
                error_message = ?,
                finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, metrics_json, output_summary, error_message, execution_id),
        )


def get_executions_for_task(task_id: int) -> List[sqlite3.Row]:
    """
    Return all execution steps for a given task_id in step_index order.
    """
    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT *
            FROM task_executions
            WHERE task_id = ?
            ORDER BY step_index ASC, id ASC
            """,
            (task_id,),
        )
        return cur.fetchall()
