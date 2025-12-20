# Bobiverse

Bobiverse is a multi-node, self-improving AI system composed of cooperating agents ("Bobs") coordinated by a central Orchestrator ("Prime Bob").

This repo currently contains the Phase 1 implementation:

- A central Orchestrator service
- One or more Node Agents running on different machines
- Docker-based deployment across machines

## Branches

- `main` — Stable, production baseline.
- `dev` — Active development: new features, experiments, refactors.

## High-Level Goals

- Distributed, Dockerised agents across multiple machines
- Central Orchestrator coordinating tasks and routing work
- Persistent task logging and metrics for future self-improvement
- Modular councils (Trading, Dev, Medical, Knowledge, Ops) plugged into the same framework

## Current Phase

**Phase 1 – Stable Orchestrator + Node Agent**

- Orchestrator receives tasks and routes them to node agents.
- Node agents run on multiple machines (server, main PC, Lenovo).
- Communication runs over the network with Dockerised components.

## Next Steps (Phase 1.5 / 2)

- Add a persistent task log (SQLite) for all user tasks and agent executions.
- Implement a Reflector process to analyse logs and suggest improvements.
- Add configuration + identity management via a shared `identity.yaml`.
- Begin modularising councils (Money, Dev, Medical, Knowledge, Ops).

For Teacher Council:

sudo systemctl restart teacher_council.service


To immediately confirm it’s back up:

systemctl status teacher_council.service


And a quick health check:

curl -s http://localhost:8013/health | jq


If you ever want to restart everything cleanly during dev, the usual order is:

sudo systemctl restart teacher_council.service
sudo systemctl restart bobiverse-orchestrator.service

Bobiverse

Bobiverse is a distributed, multi-node, self-improving AI system composed of specialised autonomous agents (“Bobs”), coordinated by a central Orchestrator (“Prime Bob”).

The system is designed to:

Solve arbitrary tasks

Learn from its own performance

Improve strategies and behaviour over time

Scale horizontally across machines

Present itself as a single unified intelligence

Core Architecture
Prime Bob (Orchestrator)

Central coordination service

Receives user tasks

Routes tasks to appropriate councils

Logs all executions

Exposes monitoring & introspection APIs

Runs on: Server (always-on node)
Default URL:

http://100.111.201.26:5080

Node Agents

Each physical machine runs a Node Agent which:

Registers itself with the Orchestrator

Reports system capabilities (CPU, RAM, load)

Hosts one or more Councils

Executes assigned tasks

Current nodes typically include:

Server (orchestrator + light councils)

Main PC (heavy LLM + data workloads)

Laptop / auxiliary machines

Councils (Bobs)

Each Bob is a dedicated microservice with:

Its own role

Its own prompt / logic

Its own learning surface

Optional vector “brain”

Implemented / Active
Dev Bob

Code analysis

Debugging

Refactoring

Patch suggestion

Runs on: Main PC
Model: Local LLM (DeepSeek / similar)

Service:

dev_council.service

Knowledge Bob

Factual question answering

Retrieval-Augmented Generation (RAG)

Long-term knowledge grounding

Backed by:

Vector database (Qdrant)

Ingested corpora (Wikipedia, PLOS, etc.)

Architect Bob

System-level reasoning

Architectural review

Evolution proposals

Structural critique

Works closely with:

Reflector Bob

Dev Bob

Reflector Bob

Periodic self-analysis engine

Reviews task logs

Identifies failure patterns

Produces:

Lessons

Proposals

Prompt tweaks

Strategy adjustments

Trigger via:

./bobctl reflector-run


Inspect results:

./bobctl reflector-lessons
./bobctl reflector-proposals

Teacher Bob

Controlled internet access

Trusted external knowledge fetcher

Source ranking & filtering

Used when internal knowledge confidence is low

Service management:

sudo systemctl restart teacher_council.service
systemctl status teacher_council.service
curl -s http://localhost:8013/health | jq

Command-Line Control (bobctl)

Primary operator interface.

Examples:

Inspect system
./bobctl show-nodes
./bobctl show-tasks
./bobctl live-status
./bobctl monitor

Submit tasks
./bobctl submit-dev "Analyse this codebase"

Reflective analysis
./bobctl reflector-run

Data & Memory
Task Database

SQLite-backed persistent store

Tracks:

Tasks

Executions

Outcomes

Councils involved

Used by:

Reflector

Architect

Future learning loops

Vector Brains

Each Bob may have:

A dedicated vector store

Its own embeddings

Domain-specific memory

Current / planned:

Knowledge Bob → encyclopaedic & scientific corpora

Teacher Bob → trusted external summaries

Reflector Bob → meta-knowledge

Identity & Personality

A shared identity.yaml defines:

System tone

Behavioural constraints

Safety posture

Long-term personality

All Bobs conform to this shared identity while maintaining role-specific behaviour.

Deployment Model

Dockerised services

systemd-managed long-running processes

Tailscale for secure inter-node communication

Nodes may join/leave without downtime

Restart Order (Development)

When restarting everything cleanly:

sudo systemctl restart teacher_council.service
sudo systemctl restart dev_council.service
sudo systemctl restart bobiverse-orchestrator.service


Node agents auto-reconnect.

Roadmap (High Level)
Phase 1 (Complete)

Orchestrator

Node Agents

Dev Council

Basic monitoring

Phase 1.5 (Complete / Ongoing)

Persistent task DB

Reflector Bob

Architect Bob

Teacher Bob

Phase 2 (Next)

Full Knowledge Bob RAG

Memory Bob

Judge Bob (multi-agent arbitration)

Ops Bob (system self-healing)

Phase 3

Autonomous experimentation

Strategy mutation

Council self-evolution

Reduced human intervention

Philosophy

Bobiverse is not a chatbot.
It is a distributed cognitive system.

Each Bob:

Specialises

Learns

Debates

Improves the whole

The system grows smarter by living, not by static training.

our active Bobiverse services are:

Role	systemd unit
Orchestrator	bobiverse-orchestrator
Memory Bob	memory_council
Architect Council	architect_council
Teacher Council	teacher_council
Ops Bob	ops_bob