from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from .utils import safe_json, utc_now_iso


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at_utc TEXT NOT NULL,
  task_id TEXT,
  module TEXT NOT NULL,
  node_id TEXT,
  status TEXT,
  summary TEXT NOT NULL,
  details_json TEXT,
  tags_json TEXT,
  artifacts_json TEXT
);

CREATE TABLE IF NOT EXISTS memory_lessons (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at_utc TEXT NOT NULL,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  tags_json TEXT,
  refs_json TEXT,
  signature TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_events_created ON memory_events(created_at_utc);
CREATE INDEX IF NOT EXISTS idx_events_module ON memory_events(module);
CREATE INDEX IF NOT EXISTS idx_events_status ON memory_events(status);
"""


class SQLiteStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(SCHEMA_SQL)
        self.conn.commit()

    # ---------- Events ----------
    def insert_event(
        self,
        created_at_utc: str,
        task_id: Optional[str],
        module: str,
        node_id: Optional[str],
        status: str,
        summary: str,
        details: Dict[str, Any],
        tags: List[str],
        artifacts: Dict[str, Any],
    ) -> int:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO memory_events
            (created_at_utc, task_id, module, node_id, status, summary, details_json, tags_json, artifacts_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at_utc,
                task_id,
                module,
                node_id,
                status,
                summary,
                safe_json(details),
                safe_json(tags),
                safe_json(artifacts),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_recent_events(self, limit: int = 200) -> List[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT * FROM memory_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return list(cur.fetchall())

    def search_events_like(
        self,
        query: str,
        module: Optional[str] = None,
        limit: int = 10,
    ) -> List[sqlite3.Row]:
        q = f"%{query}%"
        cur = self.conn.cursor()
        if module:
            cur.execute(
                """
                SELECT * FROM memory_events
                WHERE module = ?
                  AND (summary LIKE ? OR details_json LIKE ? OR tags_json LIKE ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (module, q, q, q, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM memory_events
                WHERE (summary LIKE ? OR details_json LIKE ? OR tags_json LIKE ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (q, q, q, limit),
            )
        return list(cur.fetchall())

    # ---------- Lessons ----------
    def insert_lesson_if_new(
        self,
        title: str,
        text: str,
        tags: List[str],
        refs: List[str],
        signature: str,
        created_at_utc: Optional[str] = None,
    ) -> Optional[int]:
        created = created_at_utc or utc_now_iso()
        cur = self.conn.cursor()
        try:
            cur.execute(
                """
                INSERT INTO memory_lessons
                (created_at_utc, title, text, tags_json, refs_json, signature)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (created, title, text, safe_json(tags), safe_json(refs), signature),
            )
            self.conn.commit()
            return int(cur.lastrowid)
        except sqlite3.IntegrityError:
            # signature already exists
            return None

    def get_recent_lessons(self, limit: int = 50) -> List[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT * FROM memory_lessons
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return list(cur.fetchall())
