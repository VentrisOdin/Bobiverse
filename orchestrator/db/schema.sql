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


-- ============================
-- policy_proposals: Reflector → Policy loop
-- ============================
CREATE TABLE IF NOT EXISTS policy_proposals (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_uuid    TEXT NOT NULL UNIQUE,

    -- Who created this proposal: "reflector", "human", "dev_council", etc.
    source           TEXT,

    -- High-level type of proposal
    -- e.g. "ROUTING_ADJUSTMENT", "PROMPT_UPDATE", "EXPERIMENT_PLAN"
    proposal_type    TEXT NOT NULL,

    -- Scope of what this touches (optional, for filtering)
    -- e.g. "node:test-node", "module:DEV-CODEGEN", "global"
    scope            TEXT,

    -- Arbitrary JSON content describing the change being proposed
    payload_json     TEXT NOT NULL,

    -- Natural-language explanation for humans
    rationale        TEXT,

    -- "PENDING", "APPROVED", "REJECTED", "APPLIED"
    status           TEXT NOT NULL DEFAULT 'PENDING',

    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at       TEXT,
    applied_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_policy_proposals_uuid
    ON policy_proposals(proposal_uuid);

CREATE INDEX IF NOT EXISTS idx_policy_proposals_status
    ON policy_proposals(status);

CREATE INDEX IF NOT EXISTS idx_policy_proposals_created_at
    ON policy_proposals(created_at);


-- ==========================================
-- Reflector Lessons: high-level system learnings
-- ==========================================
CREATE TABLE IF NOT EXISTS reflector_lessons (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    summary_text      TEXT NOT NULL,
    raw_snapshot_json TEXT NOT NULL,  -- JSON string of /reflector/insights at time of lesson
    source            TEXT,           -- e.g. 'manual', 'heuristic', 'llm-dev_council'
    tags              TEXT            -- comma-separated tags, e.g. 'dev_council,integration,errors'
);


-- ==========================================
-- Reflector Proposals: structured actions suggested by Reflector Brain
-- ==========================================
CREATE TABLE IF NOT EXISTS reflector_proposals (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    proposal_uuid       TEXT NOT NULL,
    proposal_type       TEXT NOT NULL, -- e.g. PROMPT_TWEAK, ROUTING_POLICY, MODULE_ISOLATION
    target_module       TEXT NOT NULL, -- e.g. dev_council, trading_council
    motivation_lesson_id INTEGER,      -- FK to reflector_lessons.id
    risk_score          INTEGER,       -- 1-5
    description         TEXT NOT NULL, -- short human summary
    action_payload_json TEXT NOT NULL, -- JSON string of the executable payload
    source              TEXT,          -- e.g. 'llm-deepseek', 'heuristic', 'manual'
    status              TEXT NOT NULL DEFAULT 'PENDING', -- PENDING, APPROVED, REJECTED, APPLIED
    applied_at          TEXT,
    FOREIGN KEY (motivation_lesson_id) REFERENCES reflector_lessons(id)
);

CREATE INDEX IF NOT EXISTS idx_reflector_proposals_uuid
    ON reflector_proposals (proposal_uuid);
