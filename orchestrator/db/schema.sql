-- orchestrator/db/schema.sql

-- ==========================
--  High-level tasks table
-- ==========================
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_uuid TEXT NOT NULL UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    high_level_type TEXT,          -- e.g. 'trading', 'dev', 'medical', 'ops'
    submitted_by TEXT,             -- e.g. 'Matt', 'system', 'scheduler'
    input_payload TEXT,            -- JSON of the original request
    final_status TEXT,             -- 'pending', 'success', 'failed', 'cancelled'
    final_result_summary TEXT,     -- short human-readable summary
    error_message TEXT             -- final error if it failed
);

-- ==============================
--  Low-level execution steps
-- ==============================
CREATE TABLE IF NOT EXISTS task_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,      -- FK to tasks.id
    step_index INTEGER NOT NULL,   -- 0,1,2,... order of actions
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    finished_at DATETIME,
    target_module TEXT,            -- e.g. 'MoneyCouncil', 'DevCouncil'
    target_node TEXT,              -- e.g. 'server', 'main-pc', 'lenovo-node'
    agent_name TEXT,               -- e.g. 'PrimeBob', 'TraderBob01'
    status TEXT,                   -- 'running', 'success', 'failed'
    metrics_json TEXT,             -- JSON blob: { "latency_ms": ..., "pnl": ... }
    output_summary TEXT,           -- short summary of this step result
    error_message TEXT,            -- error if this step failed

    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- ======================
--  Helpful indexes
-- ======================
CREATE INDEX IF NOT EXISTS idx_tasks_task_uuid
    ON tasks (task_uuid);

CREATE INDEX IF NOT EXISTS idx_exec_task_id
    ON task_executions (task_id);

CREATE INDEX IF NOT EXISTS idx_exec_target_module
    ON task_executions (target_module);
