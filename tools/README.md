# Bobiverse – Operator Manual

Bobiverse is a multi-node, self-improving AI system composed of cooperating agents ("Bobs") coordinated by a central Orchestrator ("Prime Bob").

Phase 1 establishes:

- A central Orchestrator service (Prime Bob)
- One or more Node Agents (worker Bobs) on different machines
- Councils (Dev Bob, Knowledge Bob, etc.) as specialised services
- A Reflector service for analytics + self-reflection
- A unified CLI: `bobctl`

This document is the **operator manual**: where everything lives, how to run it, and how to use `bobctl` day to day.

---

## 1. High-Level Architecture

### 1.1 Components

- **Orchestrator (Prime Bob)**  
  - FastAPI service on the **server**  
  - Receives tasks, routes them to nodes, logs everything into SQLite  
  - Exposes dev/knowledge task APIs  
  - Exposes DB inspection and reflector-facing APIs

- **Node Agents**  
  - Run on each worker machine (main PC, Lenovo, etc.)  
  - Register with Prime Bob (`/register`), send heartbeats (`/heartbeat`)  
  - Advertise capabilities (e.g. `["dev", "knowledge"]`)  
  - Pull tasks for their capabilities and call local councils

- **Councils**  
  - Specialised services running on nodes, e.g.:
    - `dev_council` – Dev Bob: code analysis, refactors, etc.
    - `knowledge_council` – Knowledge Bob: RAG / Q&A (scaffold in place)
  - Each has its own API (`/dev/tasks/next`, `/knowledge/tasks/next`, etc.)

- **Reflector**  
  - Separate FastAPI service on port **5081**  
  - Reads the same SQLite DB via `db_manager`  
  - Provides analytics and stores:
    - **lessons** (`reflector_lessons` table)
    - **proposals** (`reflector_proposals` table)
  - New: supports `bobctl reflector-run` to trigger an auto-run analysis

- **bobctl (CLI)**  
  - Lives in `~/bobiverse/tools/bobctl`  
  - Single entrypoint for:
    - Node + task inspection
    - Dev Bob usage
    - Reflector insights + runs
    - Dashboards (monitor + top)
    - DB inspection & logs

---

## 2. Directory Layout

From `~/bobiverse`:

```text
bobiverse/
│
├── orchestrator/
│   ├── main.py                 # Prime Bob (FastAPI)
│   ├── models.py               # Node + task Pydantic models
│   ├── db/
│   │   ├── db_manager.py       # SQLite helpers
│   │   ├── schema.sql          # DB schema
│   │   └── bobiverse.db        # Database file
│   ├── reflector_service.py    # Reflector API (port 5081)
│   └── logs/                   # Orchestrator logs live here
│
├── node_agent/
│   ├── main.py                 # Node Agent (polls /tasks/next etc.)
│   └── logs/                   # Node-specific logs
│
├── councils/
│   ├── dev_council/
│   │   ├── dev_council_service.py   # Dev Bob service (FastAPI)
│   │   ├── dev_council_client.py    # Node Agent client
│   │   ├── prompts/                 # Prompt templates
│   │   └── logs/
│   └── knowledge_council/           # (scaffold similarly)
│
└── tools/
    ├── bobctl                       # Main CLI
    ├── scripts/
    │   ├── show_nodes.py
    │   ├── show_tasks.py
    │   ├── show_dev.py
    │   ├── submit_dev.py
    │   ├── submit_shell.py
    │   ├── submit_python.py
    │   ├── tail_orchestrator_logs.py
    │   ├── db_inspect.py
    │   ├── dashboards/
    │   │   └── live_status.py
    │   ├── reflector_cli.py
    │   ├── reflector_lessons_cli.py
    │   ├── reflector_proposals_cli.py
    │   ├── reflector_run_cli.py     # NEW: used by `bobctl reflector-run`
    │   └── bobctl_dev_cli.py        # Dev Bob subcommand handler
    ├── monitor.py                   # Dash monitor (web/TUI)
    └── top.py                       # Task-centric TUI
```

---

## 3. Services & Ports

### Orchestrator (Prime Bob)

- **File**: `orchestrator/main.py`
- **Port**: `ORCHESTRATOR_PORT` (default 5080)
- **Health**: `GET /health`

### Reflector

- **File**: `orchestrator/reflector_service.py`
- **Port**: 5081
- **Key endpoints**:
  - `GET /reflector/summary`
  - `GET /reflector/insights`
  - `GET /reflector/lessons/recent`
  - `POST /reflector/lessons`
  - `GET /reflector/proposals/recent`
  - `POST /reflector/proposals`
  - `POST /reflector/run` ← used by `bobctl reflector-run`

### Dev Council

- **File**: `councils/dev_council/dev_council_service.py`
- **Port**: whatever you defined (e.g. 8011)
- Node Agent calls `GET /dev/tasks/next` and `POST /dev/tasks/{task_uuid}/result`

### Knowledge Council

- Similar pattern: `/knowledge/tasks/next`, `/knowledge/tasks/{task_uuid}/result`

---

## 4. Environment Variables

Set appropriately on each machine.

### 4.1 Common (Node Agent)

```bash
BOBIVERSE_NODE_NAME=data-mainpc             # unique per node
NODE_ROLE=worker                            # or 'orchestrator'
TAILSCALE_IP=100.111.x.x                    # node's Tailscale IP (optional)
ORCHESTRATOR_URL=http://100.111.201.26:5080 # Prime Bob base URL
```

### 4.2 Orchestrator

```bash
ORCHESTRATOR_NODE_NAME=prime-bob
ORCHESTRATOR_PORT=5080
```

### 4.3 Reflector

```bash
# Optional override for CLI tools:
BOBIVERSE_REFLECTOR_HOST=http://100.111.201.26:5081
ORCHESTRATOR_URL=http://100.111.201.26:5080  # used by reflector_service to read DB via API
```

### 4.4 Dev Council Node

```bash
DEV_COUNCIL_PORT=8011
# plus any LLM-related envs (e.g. OLLAMA_HOST, model name, etc.)
```

---

## 5. bobctl – Command Reference

From `~/bobiverse/tools`:

```bash
./bobctl -h
```

Current commands (from the COMMANDS registry + special ones):

### 5.1 Node & Task Inspection

**show-nodes**  
List registered nodes from the orchestrator.

```bash
./bobctl show-nodes
```

**show-tasks**  
List recent tasks from Prime Bob's in-memory task list.

```bash
./bobctl show-tasks --limit 20
```

**show-dev**  
Show Dev Council tasks recorded in the DB (via helper script).

```bash
./bobctl show-dev                     # last 20 dev tasks
./bobctl show-dev <task-uuid>        # detailed view for one task
./bobctl show-dev --limit 50
```

### 5.2 Submitting Tasks (generic / legacy paths)

**submit-dev**  
Simple, structured Dev task creation via `POST /tasks/dev`.

```bash
./bobctl submit-dev "Short description of the dev task" \
    --details "Longer explanation or notes"
```

**submit-shell** (stub for future automation)

```bash
./bobctl submit-shell "ls -la /some/path" --target-node data-mainpc
```

**submit-python** (stub for future automation)

```bash
./bobctl submit-python "print('hello')" --target-node data-mainpc
```

### 5.3 Logs & DB

**tail-orch-logs**  
Tail the orchestrator log file (`orchestrator.log`).

```bash
./bobctl tail-orch-logs
```

**db-inspect**  
Inspect tasks + executions stored in SQLite.

```bash
./bobctl db-inspect --limit 50
```

### 5.4 Live Dashboards

**live-status**  
Lightweight dashboard showing nodes + tasks (uses `dashboards.live_status`):

```bash
./bobctl live-status --interval 2.0
```

**monitor**  
Rich monitor (Dev Bob, Architect Bob view, etc.):

```bash
./bobctl monitor
./bobctl monitor --interval 1.0
```

**top**  
Task-centric TUI; "which councils/nodes are hot right now":

```bash
./bobctl top
./bobctl top --interval 0.5
```

### 5.5 Reflector Commands

These talk to the Reflector service (port 5081).

**show-reflector**  
Show overall error rates, modules, nodes, and recent failures.

```bash
./bobctl show-reflector
```

**reflector-lessons**  
List and manage Reflector lessons (wrapper around `/reflector/lessons/recent` and `/reflector/lessons`).

```bash
./bobctl reflector-lessons
```

**reflector-proposals**  
List and manage Reflector proposals (wrapper around `/reflector/proposals/recent` and `/reflector/proposals`).

```bash
./bobctl reflector-proposals
```

**reflector-run** ✅ NEW

Trigger a Reflector analysis cycle. This:

- Calls `POST /reflector/run` on the Reflector service.
- Generates a snapshot via `/reflector/insights`.
- Stores it as an auto-run lesson in `reflector_lessons`.
- Returns a summary plus counts of lessons/proposals created.

```bash
./bobctl reflector-run
./bobctl reflector-run --module dev_council --limit 200
```

Example output:

```
=== Reflector Run ===
Status  : ok
Module  : dev_council
Scope   : last 200 executions

Artifacts:
  Lessons   : 1
  Proposals : 0

Summary:
  Auto Reflector run over last 200 failures (module=dev_council). Total tasks=63, success=42, failed=16, success_rate=0.667.
```

### 5.6 Dev Bob High-Power Mode: `bobctl dev`

The `dev` subcommand sends everything after `dev` straight into `bobctl_dev_command` (in `scripts/bobctl_dev_cli.py`), which in turn talks to Dev Bob.

General pattern:

```bash
./bobctl dev <subcommand> [options...]
```

Examples (exact subcommands are defined inside `bobctl_dev_cli.py`; use `./bobctl dev --help` for the authoritative list):

**Analyse a single file:**

```bash
./bobctl dev analyse path/to/file.py
```

**Analyse all code in a directory:**

```bash
./bobctl dev analyse-dir path/to/project/
```

**Feed a JSON task spec:**

```bash
./bobctl dev from-json path/to/task.json
```

Internally, these:

1. Build a rich `input_payload` describing code, context, and requested operation.
2. Create a dev task via `POST /tasks/dev`.
3. Dev Council pulls it from `/dev/tasks/next`, calls the LLM, and writes:
   - `tasks.final_status`
   - `task_executions` row with full response in `metrics_json`.
4. `show-dev` and the dashboards let you inspect outcomes and latency.

---

## 6. Reflector Behaviour

### 6.1 Analytics Endpoints

Reflector reads the same DB as the orchestrator and exposes:

**GET /reflector/summary**  
Overall tasks, success/failure counts.

**GET /reflector/nodes/errors**  
Error rates per node.

**GET /reflector/modules/errors**  
Error rates per module / council.

**GET /reflector/errors/by_type**  
Aggregated error types from `tasks.error_type`.

**GET /reflector/strategies/summary**  
Strategy-level performance (if `strategy_name` column exists).

**GET /reflector/insights**  
Bundled snapshot used by the Reflector Brain and for lessons.

### 6.2 Lessons

**POST /reflector/lessons**  
Creates a lesson with:

- `summary_text`
- A captured snapshot of `/reflector/insights`
- `source` (manual, auto-run, etc.)
- Optional tags

**GET /reflector/lessons/recent**  
Lists recent lessons.

### 6.3 Proposals

**POST /reflector/proposals**  
Stores a proposal produced by the Reflector Brain or manually:

- `proposal_uuid`
- `proposal_type` (PROMPT_TWEAK, ROUTING_POLICY, etc.)
- `target_module`
- `risk_score`, `description`, `action_payload`, `source`

**GET /reflector/proposals/recent**

### 6.4 Auto-Run (/reflector/run)

`POST /reflector/run` payload:

```json
{
  "module": "dev_council" | null,
  "limit": 200
}
```

Behaviour (v1):

1. Calls `reflector_insights(limit_failures=limit)` to get a snapshot.
2. Builds an auto summary string.
3. Inserts a new row into `reflector_lessons` with:
   - `summary_text`
   - `raw_snapshot_json` = insights snapshot
   - `source` = "auto-run"
   - tags including "auto-run" and "module:<module or all>".
4. Returns JSON used by `bobctl reflector-run`.

---

## 7. Typical Workflows

### 7.1 Use Dev Bob on some code

Make sure:

- Orchestrator is running.
- Dev Council service is running on a node with capability `dev`.
- Node Agent is running on that node.

From `~/bobiverse/tools`:

```bash
./bobctl dev analyse path/to/file.py
# or:
./bobctl submit-dev "Refactor this module" --details "See src/foo/bar.py"
```

Inspect results:

```bash
./bobctl show-dev                # list latest dev tasks
./bobctl show-dev <task-uuid>    # full reasoning + suggestions
./bobctl monitor                 # watch dev tasks live
```

### 7.2 Run Reflector and see what it learned

```bash
./bobctl reflector-run --module dev_council --limit 200
./bobctl reflector-lessons
./bobctl reflector-proposals
./bobctl show-reflector
```

---

## 8. Restarting Components

### Orchestrator

```bash
sudo systemctl restart orchestrator.service    # if using systemd
# or:
cd ~/bobiverse/orchestrator
python main.py
```

### Reflector

```bash
sudo systemctl restart reflector.service
# or:
cd ~/bobiverse/orchestrator
python reflector_service.py
```

### Node Agent

```bash
sudo systemctl restart node_agent.service
# or:
cd ~/bobiverse/node_agent
python main.py
```

### Dev Council

```bash
sudo systemctl restart dev_council.service
# or:
cd ~/bobiverse/councils/dev_council
python dev_council_service.py
```

---

## 9. Adding New Councils (Pattern)

To add, say, **Money Council**:

1. Create `councils/money_council/` with:
   - `money_council_service.py`
   - `money_council_client.py`
   - `schemas.py`
   - `prompts/`
   - `logs/`

2. Add API endpoints in orchestrator similar to Dev/Knowledge:
   - `POST /tasks/money`
   - `GET /money/tasks/next`
   - `POST /money/tasks/{task_uuid}/result`

3. Ensure the node running it advertises `"money"` in capabilities.

4. Extend dashboards + bobctl commands as needed.

---

---

## 10. LLM Storage Locations (Main PC)

### Ollama installation

WSL path: `/home/matt/.ollama/`

### Model files

Ollama stores models at: `/home/matt/.ollama/models/`

Examples:
- `llama3:8b`
- `deepseek-coder:6.7b`
- `mistral-nemo`

You pull them via:

```bash
ollama pull llama3
ollama pull deepseek-coder:6.7b
```

### Dev Council LLM Selection

In Dev Council config:

```bash
LLM_HOST=http://localhost:11434
MODEL_NAME=deepseek-coder:6.7b
```

You can change to:

```bash
MODEL_NAME=llama3
```

---

## 11. Cluster Health Checklist After Reboot

### On the Server

```bash
systemctl status orchestrator
systemctl status node_agent
systemctl status reflector
bobctl show-nodes
bobctl councils
```

### On the Main PC

```bash
systemctl status dev_council
systemctl status node_agent
```

Everything is healthy if:

- All services show `active (running)`
- `show-nodes` shows `data-mainpc` and `server`
- `councils` displays `dev_council` as active
- Dev tasks flow end-to-end

---

## 12. Phase 5 — Unified Input Router (Future Vision)

This is the eventual goal:

**Paste anything into Bobiverse → Prime Bob decides which council handles it.**

### 12.1 Desired UX

```bash
./bobctl ask --stdin
```

Paste:
- Code
- Medical text
- Research
- Logs
- Plans
- Arbitrary mixed content

Press `Ctrl+D`.

Bobiverse automatically routes:
- Code → Dev Bob
- Medical → HALMed Council
- Trading → Money Council
- Knowledge → Knowledge Bob
- System → Ops Bob

No user needs to specify anything.

### 12.2 How it will work (Phase-5 Plan)

1. Lightweight classifier inside orchestrator
2. Orchestrator assigns `high_level_type`
3. Node Agent runs the correct council model
4. Reflector analyses routing accuracy
5. Routing becomes self-improving over time

### 12.3 Why this is Phase 5

Because it depends on:
- Multiple active councils
- Refined prompt schemas
- Reflector scoring
- Reliability of Dev Bob pipeline
- Fully stable task/execution loop

You're now completing Phase 2–3, so routing comes after that.
udo systemctl restart bobiverse-node-agent.service
# optional, but safe:
sudo systemctl restart bobiverse-orchestrator