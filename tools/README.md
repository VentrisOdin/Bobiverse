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