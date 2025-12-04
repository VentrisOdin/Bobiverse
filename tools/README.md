./bobctl show-nodes
./bobctl show-tasks --limit 5
./bobctl submit-dev "Bobctl smoke test"
./bobctl show-tasks --limit 5
bobctl — Bobiverse Command-Line Interface

The bobctl tool is the unified command-line interface for interacting with Prime Bob (the orchestrator), worker nodes, and Dev Council (Dev Bob) components of the Bobiverse.

bobctl allows you to:

Inspect nodes

Submit tasks (generic, shell, python, dev tasks)

Monitor live cluster status

Inspect completed Dev Council analyses

Debug the orchestrator DB

Tail orchestrator logs

All commands run from:

cd ~/bobiverse/tools
./bobctl <command> [args...]


You can optionally specify a different orchestrator:

./bobctl --orch-url http://<host>:<port> <command>


Default orchestrator URL (via Tailscale):

http://100.111.201.26:5080

TABLE OF CONTENTS

Node Inspection

Task Management

show-tasks

submit-dev

submit-shell

submit-python

Dev Council Introspection

show-dev

Live Monitoring

Database Debugging

Orchestrator Logs

Common Workflows

Node Inspection
🔍 show-nodes

Lists all known nodes, their roles, health, load, memory, and advertised capabilities.

./bobctl show-nodes


Example:

NAME            ROLE    LOAD   FREE_MB   LAST_SEEN                            CAPABILITIES
-------------------------------------------------------------------------------------------
data-mainpc     worker  0.012  5746      2025-12-04T18:42:18.383625Z          shell, python, dev


Use when:

Confirming node connectivity

Checking Dev node is online (dev capability)

Debugging node-agent registration

Task Management
📋 show-tasks

Lists recent tasks stored in the orchestrator DB.

./bobctl show-tasks --limit 10


Displays:

TASK       TYPE    STATUS    TIME                      SUMMARY
-------------------------------------------------------------------
f3111df8   dev     SUCCESS   2025-12-04 19:42:38        
...


Good for:

Verifying tasks were created

Tracking success and failures

Seeing Dev Council work move from PENDING → RUNNING → SUCCESS

Submitting Tasks
🧠 submit-dev

Creates a structured Dev Council task in the orchestrator DB.
This is the canonical pipeline entry for Dev Bob tasks.

./bobctl submit-dev "Fix the memory leak in foo()" --details "Investigate line 42 onward"


This writes a row into /tasks/dev shaped exactly like DevTaskRequest, which Dev Council consumes.

Dev Bob will:

Claim the task via /dev/tasks/next

Call the DeepSeek LLM via Dev Council

Return structured JSON results

Update orchestrator DB via /dev/tasks/<uuid>/result

You then view output with show-dev.

🐚 submit-shell

Run a shell command remotely on a capable node.

./bobctl submit-shell "echo hello world"


Uses high_level_type = "shell".

🐍 submit-python

Send a python snippet to a node with python capability.

./bobctl submit-python "print(2 + 2)"

Dev Council Introspection
🔬 show-dev <task_uuid>

Displays full structured Dev Council reasoning, summary, suggestions, risks, tests, etc.

./bobctl show-dev <task_uuid>


Example:

./bobctl show-dev ff4f474f-0dd3-4b82-aa81-0098285b914f


Output includes:

Task UUID

Execution ID

Node & Module

HIGH-LEVEL SUMMARY

Full Dev Council model output

Structured reasoning parsed into:

SUMMARY

REASONING

SUGGESTED CHANGES

EXAMPLE CODE

TESTS_SUGGESTED

RISKS

This is the primary introspection & debugging tool for all LLM-driven development.

Live Monitoring
📡 live-status

Shows a real-time auto-refreshing cluster dashboard.

./bobctl live-status --interval 3


Displays:

Node list (load, memory, last_seen, capabilities)

Most recent tasks

Auto-refresh loop (Ctrl+C to exit)

Perfect for monitoring the health of the entire Bobiverse.

Database Debugging
🗃️ db-inspect

Show raw rows directly from orchestrator’s SQLite DB.

./bobctl db-inspect --limit 10


Outputs:

tasks table (task_uuid, payload, status, error, timestamps)

task_executions table (execution_id, module, node, status, metrics_json)

Use this when:

Tracking errors

Inspecting malformed payloads

Seeing raw metrics_json before parsing

Orchestrator Logs
🪵 tail-orch-logs

Tail the orchestrator’s log file in real-time.

./bobctl tail-orch-logs


This wraps:

~/bobiverse/logs/orchestrator.log


Used for debugging:

Node registration

Task assignment

DB writes

Dev Council returning errors

Internal failures

Common Workflows
🧪 1. Full Dev Council Smoke Test
./bobctl submit-dev "Bobctl smoke test" --details "Ensure dev pipeline works."
./bobctl show-tasks --limit 5


Wait a few seconds → then:

./bobctl show-dev <uuid>

🚦 2. Check cluster health
./bobctl show-nodes
./bobctl live-status --interval 2

🧹 3. Debug a failing Dev Council task
./bobctl show-dev <uuid>
./bobctl db-inspect --limit 20
./bobctl tail-orch-logs

🛠 4. Run local shell/python tasks
./bobctl submit-shell "uptime"
./bobctl submit-python "print('hello')"

📜 5. Retrieve latest tasks
./bobctl show-tasks --limit 20
