-- orchestrator/db/schema.sql

PRAGMA foreign_keys = ON;

-- =========================
-- tasks: high-level requests
-- =========================
CREATE TABLE IF NOT EXISTS tasks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_uuid       TEXT NOT NULL UNIQUE,

    -- What kind of thing this was (e.g. "TRADING_IDEA", "CODE_FIX", "MEDICAL_QUERY")
    high_level_type TEXT,

    -- Raw input payload (JSON as TEXT)
    input_payload   TEXT NOT NULL,

    -- Hash of input_payload for quick similarity/dedup checks
    input_hash      TEXT,

    -- Who/what submitted it (e.g. "matt", "web_ui", "system")
    submitted_by    TEXT,

    -- 0 = normal user task, 1 = spawned by Reflector as an experiment
    is_experiment   INTEGER NOT NULL DEFAULT 0,

    -- Outcome at the whole-task level ("PENDING", "RUNNING", "SUCCESS", "FAILED", "PARTIAL")
    final_status    TEXT,

    -- Optional high-level error classification at task level
    error_type      TEXT,

    -- Optional numeric reward/score the Reflector can use later
    reward_score    REAL,

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_tasks_task_uuid       ON tasks(task_uuid);
CREATE INDEX IF NOT EXISTS idx_tasks_high_level_type ON tasks(high_level_type);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at      ON tasks(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_is_experiment   ON tasks(is_experiment);


-- ===============================
-- task_executions: each attempt/step
-- ===============================
CREATE TABLE IF NOT EXISTS task_executions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    -- FK into tasks.id
    task_id         INTEGER NOT NULL,

    -- Where we sent it
    target_module   TEXT,      -- e.g. "dev_council", "money_council"
    target_node     TEXT,      -- e.g. "main_pc", "lenovo_node"

    -- Strategy/config variant label (prompt version, algorithm name, etc.)
    strategy_name   TEXT,

    -- "PENDING", "RUNNING", "SUCCESS", "FAILED", "TIMEOUT"
    status          TEXT,

    -- Shortened/summary of the output (full output can live elsewhere if huge)
    output_summary  TEXT,
    output_hash     TEXT,

    -- More fine-grained error label if needed
    error_type      TEXT,

    -- Execution metrics
    latency_ms      INTEGER,
    metrics_json    TEXT,      -- arbitrary JSON blob as TEXT

    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT,

    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_exec_task_id       ON task_executions(task_id);
CREATE INDEX IF NOT EXISTS idx_exec_target_module ON task_executions(target_module);
CREATE INDEX IF NOT EXISTS idx_exec_target_node   ON task_executions(target_node);
CREATE INDEX IF NOT EXISTS idx_exec_status        ON task_executions(status);
CREATE INDEX IF NOT EXISTS idx_exec_started_at    ON task_executions(started_at);
