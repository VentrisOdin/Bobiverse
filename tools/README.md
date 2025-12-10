bobctl — Bobiverse Command-Line Interface

The bobctl tool is the unified command-line interface for interacting with:

🧠 Prime Bob (the Orchestrator)

🏗️ Node Agents (worker machines)

👨‍💻 Dev Council (LLM-powered Dev Bob)

🪞 Reflector (self-learning analytics engine)

It is the administrative shell for the entire Bobiverse distributed AI system.

Run bobctl from:

cd ~/bobiverse/tools
./bobctl <command> [args...]


To use a non-default orchestrator:

./bobctl --orch-url http://<host>:<port> <command>


Default orchestrator URL (Tailscale):

http://100.111.201.26:5080

TABLE OF CONTENTS

Node Inspection

Task Management

Submitting Tasks

Dev Council Introspection

Live Monitoring

Database Debugging

Orchestrator Logs

Common Workflows

Service Locations & File Paths

Starting Everything Manually (uvicorn)

Systemd Unit Files

Systemd Status & Logs

LLM Storage Locations (Main PC)

Cluster Health Checklist

1. Node Inspection
🔍 show-nodes

Lists all known nodes, their roles, loads, memory, and capability flags.

./bobctl show-nodes


Example:

NAME            ROLE    LOAD   FREE_MB   LAST_SEEN                            CAPABILITIES
-------------------------------------------------------------------------------------------
data-mainpc     worker  0.012  5746      2025-12-04T18:42:18.383625Z          shell, python, dev


Use this to:

Confirm nodes are online

Ensure Dev node is available

Debug node-agent registration

2. Task Management
📋 show-tasks
./bobctl show-tasks --limit 10


Shows:

Task UUID

Type

Status (PENDING → RUNNING → SUCCESS/FAILURE)

Summary

Useful for tracking flow through the entire pipeline.

3. Submitting Tasks
🧠 submit-dev

Submit a Dev Council task:

./bobctl submit-dev "Fix memory leak" --details "Investigate foo() line 42"


Pipeline:

Task enters orchestrator database

Node Agent requests work

Dev Council calls DeepSeek/LLama3 LLM

Structured JSON returned

DB updated

View with show-dev

🐚 submit-shell
./bobctl submit-shell "echo hello"


Runs on a node with shell capability.

🐍 submit-python
./bobctl submit-python "print(2 + 2)"


Runs via node-agent Python executor.

4. Dev Council Introspection
🔬 show-dev <uuid>

Shows complete structured Dev Council output, including:

Summary

Reasoning

Suggested Changes

Example Code

Tests Suggested

Risks

./bobctl show-dev <task_uuid>

📝 Dev Bob — Code Analysis via bobctl

Dev Bob is the Dev Council agent that reviews code, suggests improvements, and surfaces risks.

Single file analysis

Analyse one file and get feedback:

cd ~/bobiverse/tools
./bobctl dev analyse bobctl.py --ask "Review this CLI, find issues, and suggest improvements."


Then inspect the result:

./bobctl show-dev <task-uuid>


show-dev prints:

Summary

Reasoning

Suggested changes (if any)

Test ideas

Risks

stdin mode (paste code like ChatGPT)

Use --stdin to paste any code from anywhere:

./bobctl dev analyse --stdin --ask "Explain this code and point out any bugs or bad patterns."
# paste code here
# Ctrl+D to finish (Linux/Mac) or Ctrl+Z + Enter (Windows)


Then:

./bobctl show-tasks --limit 5
./bobctl show-dev <latest-dev-task-uuid>


Directory analysis

Analyse an entire directory (automatically tar+base64 encoded):

./bobctl dev analyse ~/bobiverse/orchestrator --ask "Review the orchestrator service architecture."


Interpreting results

If SUMMARY and REASONING mention your file and specific issues → Dev Bob understood the context.

If SUGGESTED CHANGES is empty, treat it as "no concrete patch suggested yet" – the analysis is still useful but not patch-ready.

If you want more aggressive suggestions, use a stronger --ask, e.g.:

./bobctl dev analyse bobctl.py \
  --ask "Be very picky. Propose concrete refactors with clear justifications."


Available intents

analyse — General code review

fix — Focus on bugs and fixes

refactor — Focus on structural improvements

Example:

./bobctl dev fix my_script.py --ask "Find and fix any bugs."
./bobctl dev refactor my_service/ --ask "Improve code quality and structure."

5. Live Monitoring
📡 live-status
./bobctl live-status --interval 3


Displays:

Auto-updating node list

Recent tasks

Health metrics

Great for running on a second monitor.

6. Database Debugging
🗃️ db-inspect
./bobctl db-inspect --limit 10


Reads raw rows from:

tasks

task_executions

Use this to inspect malformed tasks or reflector metrics.

7. Orchestrator Logs
🪵 tail-orch-logs
./bobctl tail-orch-logs


Wraps:

~/bobiverse/logs/orchestrator.log


Shows:

Node registration

Task routing

Dev Council errors

Reflector calls

8. Common Workflows
🧪 Smoke Test Dev Council
./bobctl submit-dev "Bobctl smoke test"
./bobctl show-tasks --limit 5
./bobctl show-dev <uuid>

🚦 Check Cluster Health
./bobctl show-nodes
./bobctl live-status --interval 2

🧹 Debug failing Dev Council task
./bobctl show-dev <uuid>
./bobctl db-inspect --limit 20
./bobctl tail-orch-logs

9. Service Locations & File Paths
~/bobiverse/
├── orchestrator/
│   ├── main.py
│   └── db/
│       ├── db_manager.py
│       ├── schema.sql
│       └── bobiverse.db
├── node_agent/
│   └── node_agent_service.py
├── councils/
│   └── dev_council/
│       ├── dev_council_service.py
│       ├── schemas.py
│       └── model_prompts/
├── reflector/
│   └── reflector_service.py
├── tools/
│   └── bobctl
└── logs/
    ├── orchestrator.log
    ├── node_agent.log
    ├── dev_council.log
    └── reflector.log

10. Starting Everything Manually (uvicorn)

Run inside .venv
All commands assume cd ~/bobiverse

Orchestrator
uvicorn orchestrator.main:app --host 0.0.0.0 --port 5080 --reload

Node Agent (server)
uvicorn node_agent.node_agent_service:app --host 0.0.0.0 --port 7000 --reload

Node Agent (main PC)

Typical port: 8001

uvicorn node_agent.node_agent_service:app --host 0.0.0.0 --port 8001 --reload

Dev Council (main PC)

Port: 8011

uvicorn councils.dev_council.dev_council_service:app --host 0.0.0.0 --port 8011 --reload

Reflector (server)
uvicorn reflector.reflector_service:app --host 0.0.0.0 --port 5090 --reload

11. Systemd Unit Files

Place in:

/etc/systemd/system/


Enable all:

sudo systemctl enable orchestrator.service
sudo systemctl enable node_agent.service
sudo systemctl enable dev_council.service
sudo systemctl enable reflector.service


Start/Stop:

sudo systemctl restart orchestrator.service
sudo systemctl status dev_council.service


Log tail:

journalctl -u orchestrator.service -f
journalctl -u dev_council.service -f

12. LLM STORAGE LOCATIONS (MAIN PC)
Ollama installation

WSL path:

/home/matt/.ollama/

Model files

Ollama stores models at:

/home/matt/.ollama/models/


Examples:

llama3:8b  
deepseek-coder:6.7b  
mistral-nemo  


You pull them via:

ollama pull llama3
ollama pull deepseek-coder:6.7b

Dev Council LLM Selection

In Dev Council config:

LLM_HOST=http://localhost:11434
MODEL_NAME=deepseek-coder:6.7b


You can change to:

MODEL_NAME=llama3

13. Cluster Health Checklist After Reboot
On the Server
systemctl status orchestrator
systemctl status node_agent
systemctl status reflector
bobctl show-nodes
bobctl councils

On the Main PC
systemctl status dev_council
systemctl status node_agent

Everything is healthy if:

All services show active (running)

show-nodes shows data-mainpc and server

councils displays dev_council as active

Dev tasks flow end-to-end

14. Dev Bob — Code Analysis / Refactor Engine

Dev Bob is the LLM-powered code assistant of the Bobiverse.
It accepts:

A file

A directory

Raw text

A code snippet pasted into STDIN

Arbitrary instructions

And returns:

Summary

Reasoning

Suggested changes

Full structured JSON

Safe fallback analysis

🔧 14.1 Single File Mode
./bobctl dev analyse myscript.py --ask "Find issues and propose refactor."


Dev Bob receives:

✓ The file's contents
✓ Your instructions
✓ Its intent ("analyse")

📁 14.2 Directory Mode
./bobctl dev analyse ~/myproject --ask "Give architectural review."


bobctl will:

Tar + base64 encode the directory

Create a file manifest

Send every file to Dev Bob as context

This is ideal for:

Reviewing an entire service

Scanning a multi-file module

📋 14.3 STDIN Paste Mode (ChatGPT-Style)

This is the "paste anything" mode.

./bobctl dev analyse --stdin --ask "Explain what this does and fix any bugs."


Paste your code (any language, any size), then press:

Ctrl+D (Linux/Mac)

Ctrl+Z + Enter (Windows)

Dev Bob will:

Treat the entire pasted content as the code

Create a synthetic file bobctl_dev/stdin_blob

Analyse exactly what you pasted

This replicates ChatGPT's "paste code into the chat box" but inside your distributed AI system.

🔍 14.4 View the Analysis
./bobctl show-dev <task_uuid>


You'll see:

Summary

Reasoning

Suggested changes

Example code

Tests suggested

Risks

The raw JSON output

🔄 14.5 End-to-End Pipeline (Summary)

bobctl creates a task with payload

Orchestrator logs it

Node Agent picks it up

Dev Council loads:

context_files

your code (from JSON details)

DeepSeek/Llama3 returns JSON

Results stored + visible via bobctl

15. How Dev Bob Processes Code (Internals)

This is how your code enters the LLM context.

15.1 bobctl generates a structured payload

For files, dirs, or stdin, bobctl produces:

{
  "mode": "single_file | directory | stdin_blob",
  "filename": "...",
  "code": "...",
  "instructions": "...",
  "intent": "analyse|fix|refactor"
}


This is JSON-encoded inside req.details.

15.2 Orchestrator stores it untouched

It doesn't parse or interfere — this preserves isolation and prevents breakage.

15.3 Node Agent delivers the payload to Dev Council

Exact contents delivered.

15.4 Dev Council parses the incoming JSON

If details contains JSON with "code":

It extracts the code

Creates a synthetic context file:

bobctl_dev/<filename>


Adds it to context_files

Merges with orchestrator context (normal mode)

Or replaces orchestrator context (solo mode)

This now becomes the entire context block for DeepSeek/Llama.

15.5 The LLM sees all code as a list of files

Example:

### FILE: bobctl_dev/bobctl.py
<full file contents>

### FILE: orchestrator/main.py
<existing orchestrator context>


From there, Dev Bob generates:

Summary

Reasoning

JSON diffs

Proposed fixes

All validated before returning.

16. Phase 5 — Unified Input Router (Future Vision)

This is the eventual goal:

Paste anything into Bobiverse → Prime Bob decides which council handles it.

16.1 Desired UX
./bobctl ask --stdin


Paste:

Code

Medical text

Research

Logs

Plans

Arbitrary mixed content

Press Ctrl+D.

Bobiverse automatically routes:

Code → Dev Bob

Medical → HALMed Council

Trading → Money Council

Knowledge → Knowledge Bob

System → Ops Bob

No user needs to specify anything.

16.2 How it will work (Phase-5 Plan)

Lightweight classifier inside orchestrator

Orchestrator assigns high_level_type

Node Agent runs the correct council model

Reflector analyses routing accuracy

Routing becomes self-improving over time

16.3 Why this is Phase 5

Because it depends on:

Multiple active councils

Refined prompt schemas

Reflector scoring

Reliability of Dev Bob pipeline

Fully stable task/execution loop

You're now completing Phase 2–3, so routing comes after that.