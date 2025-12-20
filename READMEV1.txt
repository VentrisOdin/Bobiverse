# Bobiverse Ultimate Operator & Architect Guide

---

> **This is the canonical, full-scope operational, architectural, and philosophical guide to the Bobiverse.**
> If something is not documented here, it is either intentionally undefined or not yet part of the system.

---

## 0. Executive Summary

Bobiverse is a **distributed cognitive infrastructure**, not a chatbot, not a single agent, and not an autonomous toy system.

It is designed as a **living AI organism** composed of specialised agents (“Bobs”) that cooperate and compete under the coordination of a central Orchestrator (“Prime Bob”).

The system exists to:

* Solve complex, real-world problems
* Learn from execution outcomes
* Improve strategies and behaviour over time
* Scale horizontally across heterogeneous machines
* Remain observable, debuggable, and safe as intelligence increases

**Doctrine:**

> *Intelligence is an emergent property of stable substrate.*

---

## 1. Vision & Design Philosophy

### 1.1 What Bobiverse Is

* A multi-node AI system
* A federation of specialist intelligences
* A long-lived cognitive substrate
* A platform for continuous learning and experimentation

### 1.2 What Bobiverse Is NOT

* ❌ A chatbot
* ❌ A monolithic “god model”
* ❌ A self-modifying codebase
* ❌ An unsupervised autonomous agent

### 1.3 Core Principles

1. **Orchestration over autonomy** – no Bob acts independently
2. **Specialisation over generalisation** – each Bob has a narrow role
3. **Memory before reasoning** – knowledge must be grounded
4. **Reflection before evolution** – change follows evidence
5. **Human-in-the-loop by default** – autonomy is earned, not assumed

---

## 2. Current Operational Reality

### 2.1 Active Phase

**Phase 1.5 – Cognitive Infrastructure & Reflection**

This phase focuses on building the foundations required for safe, scalable intelligence.

### 2.2 What Is Live Right Now

* Prime Bob (Orchestrator)
* Distributed Node Agents
* Councils: Dev, Architect, Teacher, Ops, Memory
* Reflector (advisory analysis)
* Persistent task database (SQLite)
* Vector memory infrastructure (Qdrant)

### 2.3 What Is Intentionally Disabled

* Autonomous self-improvement
* Silent learning loops
* Self-modifying prompts or code
* Council-to-council direct control

---

## 3. High-Level System Architecture

### 3.1 Prime Bob – The Orchestrator

**Role:** Central nervous system

Responsibilities:

* Accept all user tasks
* Decide *what* should act
* Decide *where* it should run
* Track execution state
* Persist outcomes
* Expose system introspection

**Authoritative Truth:**

> If Prime Bob didn’t log it, it didn’t happen.

**Runs on:** Always-on server

**Base URL:**

```
http://100.111.201.26:5080
```

---

### 3.2 Node Agents

Each physical machine runs a Node Agent.

Responsibilities:

* Register with Orchestrator
* Advertise capabilities (CPU, RAM, load)
* Host one or more Councils
* Execute assigned work

**Design Rule:**

> Node Agents execute; they do not decide.

Typical topology:

* **Server:** Orchestrator, light councils
* **Main PC:** Heavy LLMs, vector ingest, data-heavy tasks
* **Aux Nodes:** Opportunistic or specialised workloads

Nodes may join or leave dynamically.

---

## 4. Mental Model – How Bobiverse Thinks

This section prevents architectural mistakes.

### 4.1 Cognitive Flow

1. User expresses intent
2. Prime Bob interprets and routes
3. Node Agent executes via a Council
4. Results are persisted
5. Reflector analyses history
6. Humans approve or reject evolution

No Bob is sentient.
No Bob has authority.
Prime Bob coordinates everything.

### 4.2 Councils Are Tools, Not Minds

Councils:

* Do not self-task
* Do not self-route
* Do not self-modify

They are **specialist cognitive instruments**.

---

## 5. Councils (Bobs) – Full Reference

### 5.1 Dev Bob

**Purpose:** Code intelligence

Capabilities:

* Static code analysis
* Debugging
* Refactoring
* Patch and diff generation

**Runs on:** Main PC

**Model:** Local LLM (DeepSeek-class)

**Service:**

```
dev_council.service
```

---

### 5.2 Knowledge Bob

**Purpose:** Grounded factual reasoning

Capabilities:

* Retrieval-Augmented Generation (RAG)
* Long-term factual grounding
* Multi-source synthesis

**Backed by:**

* Qdrant vector database
* Encyclopaedic & scientific corpora (Wikipedia, PLOS)

---

### 5.3 Architect Bob

**Purpose:** Structural and system reasoning

Capabilities:

* Architectural critique
* Design review
* Evolution proposals

Collaborates with:

* Reflector Bob
* Dev Bob

---

### 5.4 Reflector Bob

**Purpose:** Meta-cognition (advisory only)

Capabilities:

* Analyse execution logs
* Detect failure patterns
* Surface lessons and proposals

**Never executes changes.**

Commands:

```
./bobctl reflector-run
./bobctl reflector-lessons
./bobctl reflector-proposals
```

---

### 5.5 Teacher Bob

**Purpose:** Controlled internet access

Capabilities:

* Trusted external knowledge retrieval
* Source ranking and trust scoring
* Definition-first bias

**Service management:**

```
sudo systemctl restart teacher_council.service
systemctl status teacher_council.service
curl -s http://localhost:8013/health | jq
```

---

### 5.6 Ops Bob

**Purpose:** System observability

Capabilities:

* Health monitoring
* Metrics collection
* Operational reporting

Self-healing is a **future phase** feature.

---

## 6. Command-Line Operations (bobctl)

`bobctl` is the primary operator interface.

### 6.1 Inspection & Monitoring

```
./bobctl show-nodes
./bobctl show-tasks
./bobctl live-status
./bobctl monitor
./bobctl top
```

### 6.2 Task Submission

```
./bobctl submit-dev "Analyse this codebase"
./bobctl submit-shell "Run diagnostic"
./bobctl submit-python "Check data integrity"
```

### 6.3 Reflection & Analysis

```
./bobctl reflector-run
```

---

## 7. Data, Memory & Knowledge

### 7.1 Task Database

SQLite-backed canonical record.

Tracks:

* Task intent
* Execution metadata
* Councils involved
* Outcomes

This database is **never ephemeral**.

---

### 7.2 Vector Memory (Qdrant)

Vector stores provide semantic grounding.

Rules:

* Bulk ingest first
* Index optimisation later
* Never mix experimental data with canonical corpora

---

## 8. Identity, Personality & Safety

A shared `identity.yaml` defines:

* System tone
* Behavioural constraints
* Safety posture
* Long-term personality

All Councils conform to this identity.

---

## 9. Deployment & Operations

* Dockerised services
* systemd-managed daemons
* Tailscale-secured networking

### Restart Order (Dev)

```
sudo systemctl restart teacher_council.service
sudo systemctl restart dev_council.service
sudo systemctl restart bobiverse-orchestrator.service
```

Node Agents auto-reconnect.

---

## 10. Recovery Playbooks (Essential)

### Orchestrator Not Responding

1. Check service:

```
systemctl status bobiverse-orchestrator
```

2. Restart:

```
sudo systemctl restart bobiverse-orchestrator
```

### Council Fails Health Check

1. Restart council
2. Verify `/health` endpoint
3. Check logs

---

## 11. Roadmap

### Phase 2 – Intelligence Assembly

* Full Knowledge Bob reasoning
* Memory Bob consolidation
* Judge Bob (multi-agent arbitration)
* Ops Bob remediation

### Phase 3 – Evolution

* Autonomous experimentation
* Strategy mutation
* Council self-improvement

---

## 12. Active Services

| Role              | systemd unit           |
| ----------------- | ---------------------- |
| Orchestrator      | bobiverse-orchestrator |
| Memory Bob        | memory_council         |
| Architect Council | architect_council      |
| Teacher Council   | teacher_council        |
| Ops Bob           | ops_bob                |

---

## Final Doctrine

> Bobiverse grows smarter by living, not by static training.

> Stability precedes intelligence.

> Control precedes autonomy.
