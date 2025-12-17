# councils/ops_bob/app.py
from __future__ import annotations

import os
import time
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


# =========================
# Config
# =========================
OPS_BOB_API_KEY = os.getenv("OPS_BOB_API_KEY", "").strip()  # optional for Phase 1.5A
DEGRADE_AFTER_S = int(os.getenv("OPS_DEGRADE_AFTER_S", "15"))  # start aging penalty
UNROUTABLE_AFTER_S = int(os.getenv("OPS_UNROUTABLE_AFTER_S", "30"))  # hard cutoff

app = FastAPI(
    title="Ops Bob v1",
    description="Fleet health + routing hints with aging cutoffs",
    version="1.0.0",
)

# =========================
# Models
# =========================
class ServiceStatus(BaseModel):
    name: str
    port: Optional[int] = None
    ok: bool
    last_checked_ts: float = Field(default_factory=lambda: time.time())
    detail: Optional[str] = None


class OpsReport(BaseModel):
    node_id: str
    ts: float = Field(default_factory=lambda: time.time())

    cpu_pct: Optional[float] = None
    ram_pct: Optional[float] = None
    disk_pct: Optional[float] = None
    load_1m: Optional[float] = None

    services: List[ServiceStatus] = Field(default_factory=list)
    counters: Dict[str, int] = Field(default_factory=dict)  # optional


class NodeHint(BaseModel):
    node_id: str
    last_seen_s: float
    routable: bool
    health_score: float
    metrics: Dict[str, Any] = Field(default_factory=dict)
    services: List[ServiceStatus] = Field(default_factory=list)


# =========================
# In-memory state (Day-1)
# =========================
STATE: Dict[str, Dict[str, Any]] = {}


def _auth_if_configured(x_api_key: Optional[str]) -> None:
    """Optional auth gate (Phase 1.5A: recommended if you expose beyond tailnet)."""
    if not OPS_BOB_API_KEY:
        return
    if (x_api_key or "").strip() != OPS_BOB_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def _aging_factor(age_s: float) -> float:
    """
    1.0 when fresh, decays hard after DEGRADE_AFTER_S,
    reaches 0.0 at UNROUTABLE_AFTER_S.
    """
    if age_s <= DEGRADE_AFTER_S:
        return 1.0
    if age_s >= UNROUTABLE_AFTER_S:
        return 0.0
    # linear decay between thresholds
    span = max(1.0, float(UNROUTABLE_AFTER_S - DEGRADE_AFTER_S))
    return max(0.0, 1.0 - ((age_s - DEGRADE_AFTER_S) / span))


def _base_health_from_metrics(cpu: Optional[float], ram: Optional[float], disk: Optional[float], load_1m: Optional[float]) -> float:
    """
    Very simple scoring: start at 1.0 and subtract penalties.
    Keep it stable and explainable for Phase 1.5A.
    """
    score = 1.0

    def penalty(pct: Optional[float], soft: float, hard: float, weight: float) -> float:
        if pct is None:
            return 0.0
        if pct <= soft:
            return 0.0
        if pct >= hard:
            return weight
        # linear between soft and hard
        return weight * ((pct - soft) / (hard - soft))

    score -= penalty(cpu, soft=60, hard=95, weight=0.30)
    score -= penalty(ram, soft=65, hard=95, weight=0.30)
    score -= penalty(disk, soft=75, hard=95, weight=0.20)

    # load penalty (light touch; many boxes differ)
    if load_1m is not None:
        if load_1m > 4:
            score -= 0.10
        if load_1m > 8:
            score -= 0.10

    return max(0.0, min(1.0, score))


@app.post("/ops/report")
def ops_report(report: OpsReport, x_api_key: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    _auth_if_configured(x_api_key)

    STATE[report.node_id] = {
        "last_ts": report.ts,
        "cpu_pct": report.cpu_pct,
        "ram_pct": report.ram_pct,
        "disk_pct": report.disk_pct,
        "load_1m": report.load_1m,
        "services": report.services,
        "counters": report.counters,
    }

    return {"ok": True, "node_id": report.node_id, "stored_ts": report.ts}


@app.get("/ops/routing/hints", response_model=List[NodeHint])
def routing_hints(x_api_key: Optional[str] = Header(default=None)) -> List[NodeHint]:
    _auth_if_configured(x_api_key)

    now = time.time()
    hints: List[NodeHint] = []

    for node_id, s in STATE.items():
        age_s = max(0.0, now - float(s.get("last_ts", 0.0)))
        routable = age_s <= UNROUTABLE_AFTER_S

        base = _base_health_from_metrics(
            s.get("cpu_pct"),
            s.get("ram_pct"),
            s.get("disk_pct"),
            s.get("load_1m"),
        )
        age_mult = _aging_factor(age_s)
        health = max(0.0, min(1.0, base * age_mult))

        hints.append(
            NodeHint(
                node_id=node_id,
                last_seen_s=round(age_s, 3),
                routable=routable,
                health_score=round(health, 4),
                metrics={
                    "cpu_pct": s.get("cpu_pct"),
                    "ram_pct": s.get("ram_pct"),
                    "disk_pct": s.get("disk_pct"),
                    "load_1m": s.get("load_1m"),
                    "counters": s.get("counters", {}),
                },
                services=s.get("services", []),
            )
        )

    # Highest health first (nice for humans + orchestrator)
    hints.sort(key=lambda h: (h.routable, h.health_score), reverse=True)
    return hints


@app.get("/ops/stats")
def stats() -> Dict[str, Any]:
    now = time.time()
    total = len(STATE)
    unroutable = 0
    for _, s in STATE.items():
        age_s = max(0.0, now - float(s.get("last_ts", 0.0)))
        if age_s > UNROUTABLE_AFTER_S:
            unroutable += 1
    return {
        "ok": True,
        "nodes_seen": total,
        "nodes_unroutable": unroutable,
        "degrade_after_s": DEGRADE_AFTER_S,
        "unroutable_after_s": UNROUTABLE_AFTER_S,
        "auth_enabled": bool(OPS_BOB_API_KEY),
    }
