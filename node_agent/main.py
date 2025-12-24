#!/usr/bin/env python3
"""
Bobiverse Node Agent (prime-bob)

- Registers node with Orchestrator: POST {ORCHESTRATOR_URL}/register
- Sends heartbeat to Orchestrator: POST {ORCHESTRATOR_URL}/heartbeat
- Probes local council health endpoints and reports active_councils
"""

import os
import time
import socket
import logging
from typing import Any, Dict, List

import requests
import psutil


# ----------------------------
# Logging
# ----------------------------
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s [node_agent] %(levelname)s: %(message)s",
)
log = logging.getLogger("node_agent")


# ----------------------------
# Env helpers
# ----------------------------
def env_str(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def env_int(key: str, default: int) -> int:
    v = os.getenv(key)
    if v is None or not v.strip():
        return default
    try:
        return int(v.strip())
    except ValueError:
        return default


# ----------------------------
# Config
# ----------------------------
NODE_NAME = env_str("BOBIVERSE_NODE_NAME", "prime-bob")
NODE_ROLE = env_str("NODE_ROLE", "server")  # must be "server" or "worker"
TAILSCALE_IP = env_str("TAILSCALE_IP", "")
ORCH_URL = env_str("ORCHESTRATOR_URL", "http://127.0.0.1:5080").rstrip("/")
HEARTBEAT_INTERVAL_SEC = env_int("HEARTBEAT_INTERVAL_SEC", 5)
HTTP_TIMEOUT_SEC = float(env_str("HTTP_TIMEOUT_SEC", "1.5"))

# These are "councils" running on prime-bob that we want to show as live in Bridge.
SERVICES = [
    {"name": "orchestrator",    "host": "127.0.0.1", "port": 5080, "health_path": "/health"},
    {"name": "reflector",       "host": "127.0.0.1", "port": 5081, "health_path": "/reflector/summary"},
    {"name": "architect",       "host": "127.0.0.1", "port": 8012, "health_path": "/health"},
    {"name": "teacher_council", "host": "127.0.0.1", "port": 8013, "health_path": "/health"},
    {"name": "ops_bob",         "host": "127.0.0.1", "port": 8014, "health_path": "/ops/stats"},
    {"name": "memory_council",  "host": "127.0.0.1", "port": 8031, "health_path": "/health"},
]

# Reflector is typically CLI/batch (bobctl reflector-run), not a daemon.
# We'll report it as a capability (not "live") unless/until it has an HTTP service.
CAPABILITIES: List[str] = ["reflector"]


# ----------------------------
# Node registration
# ----------------------------
def register_node() -> bool:
    url = f"{ORCH_URL}/register"
    payload = {
        "name": NODE_NAME,
        "role": NODE_ROLE,              # must be "server" or "worker"
        "hostname": socket.gethostname(),
        "tailscale_ip": TAILSCALE_IP,   # required by orchestrator
    }
    try:
        r = requests.post(url, json=payload, timeout=3.0)
        if 200 <= r.status_code < 300:
            log.info("Registered node '%s' OK", NODE_NAME)
            return True
        log.warning("Register rejected: status=%s body=%s", r.status_code, (r.text or "")[:300])
        return False
    except Exception as e:
        log.warning("Register error: %s", e)
        return False


# ----------------------------
# Service probing
# ----------------------------
def probe_service(svc: Dict[str, Any]) -> Dict[str, Any]:
    url = f"http://{svc['host']}:{svc['port']}{svc.get('health_path','/health')}"
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT_SEC)
        ok = 200 <= r.status_code < 300
        return {
            "name": svc["name"],
            "port": svc["port"],
            "ok": ok,
            "last_checked_ts": time.time(),
            "detail": None if ok else f"status={r.status_code}",
        }
    except Exception as e:
        return {
            "name": svc["name"],
            "port": svc["port"],
            "ok": False,
            "last_checked_ts": time.time(),
            "detail": str(e)[:200],
        }


# ----------------------------
# Heartbeat payload
# ----------------------------
def build_payload() -> Dict[str, Any]:
    checks = [probe_service(s) for s in SERVICES]
    active = [c["name"] for c in checks if c.get("ok")]

    payload: Dict[str, Any] = {
        # Orchestrator persists these fields (we saw them in /nodes)
        "name": NODE_NAME,
        "role": NODE_ROLE,
        "tailscale_ip": TAILSCALE_IP,
        "capabilities": CAPABILITIES,       # list of strings is fine
        "active_councils": active,          # THIS is what Bridge should use for "live"
        "load": psutil.cpu_percent(interval=None),
        "free_memory_mb": int(psutil.virtual_memory().available / (1024 * 1024)),
        # Keep ts if you want; even if it's not persisted, harmless
        "ts": int(time.time()),
        # Optional: keep raw checks for debugging (orchestrator may drop it; fine)
        "service_checks": checks,
    }
    return payload


def post_heartbeat(payload: Dict[str, Any]) -> bool:
    url = f"{ORCH_URL}/heartbeat"
    try:
        r = requests.post(url, json=payload, timeout=3.0)
        if 200 <= r.status_code < 300:
            return True
        log.warning("Heartbeat rejected: status=%s body=%s", r.status_code, (r.text or "")[:250])
        return False
    except Exception as e:
        log.warning("Heartbeat error posting to %s: %s", url, e)
        return False


# ----------------------------
# Main loop
# ----------------------------
def main() -> None:
    log.info(
        "Starting Node Agent: name=%s role=%s tailscale_ip=%s orch=%s interval=%ss",
        NODE_NAME, NODE_ROLE, TAILSCALE_IP, ORCH_URL, HEARTBEAT_INTERVAL_SEC
    )

    register_node()

    while True:
        payload = build_payload()
        ok = post_heartbeat(payload)

        total = len(SERVICES)
        up = len(payload.get("active_councils", []))
        log.info("heartbeat=%s active_councils=%s/%s", "OK" if ok else "FAIL", up, total)

        time.sleep(HEARTBEAT_INTERVAL_SEC)


if __name__ == "__main__":
    main()
