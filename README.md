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