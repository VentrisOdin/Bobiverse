# orchestrator/ops_reporter.py
import os, time, requests, psutil
from typing import Any, Dict, List

OPS_BOB_URL = os.getenv("OPS_BOB_URL", "http://127.0.0.1:8014").rstrip("/")
OPS_REPORT_INTERVAL_S = float(os.getenv("OPS_REPORT_INTERVAL_S", "10"))
OPS_REPORT_TIMEOUT_S = float(os.getenv("OPS_REPORT_TIMEOUT_S", "2.0"))

# server node id (separate from data-mainpc)

# Always use orchestrator node name for reporting
ORCHESTRATOR_NODE_NAME = os.getenv("ORCHESTRATOR_NODE_NAME", "prime-bob")
OPS_NODE_ID = ORCHESTRATOR_NODE_NAME


# service endpoints local to the server
TEACHER_URL = os.getenv("TEACHER_COUNCIL_URL", "http://127.0.0.1:8013").rstrip("/")
ORCH_URL = os.getenv("ORCHESTRATOR_URL_LOCAL", "http://127.0.0.1:5080").rstrip("/")
ARCHITECT_URL = os.getenv("ARCHITECT_COUNCIL_URL", "http://127.0.0.1:8012").rstrip("/")

SESSION = requests.Session()




def _check_http_ok(url: str, timeout_s: float = 1.0) -> tuple[bool, str | None]:
    try:
        r = SESSION.get(url, timeout=timeout_s)
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}"

        # If JSON, optionally validate {"status":"ok"} when present
        try:
            j = r.json()
            if isinstance(j, dict) and "status" in j and j.get("status") != "ok":
                return False, f"bad status: {j.get('status')}"
        except Exception:
            pass

        return True, None
    except Exception as e:
        return False, str(e)

# Only report teacher_council with port (as required)

def build_services() -> List[Dict[str, Any]]:
    # Teacher
    try:
        teacher_port = int(TEACHER_URL.rsplit(":", 1)[-1])
    except Exception:
        teacher_port = 8013
    teacher_health = f"http://localhost:{teacher_port}/health"
    teacher_ok, teacher_detail = _check_http_ok(teacher_health, timeout_s=1.0)

    # Orchestrator
    try:
        orch_port = int(ORCH_URL.rsplit(":", 1)[-1])
    except Exception:
        orch_port = 5080
    orch_health = f"http://localhost:{orch_port}/health"
    orch_ok, orch_detail = _check_http_ok(orch_health, timeout_s=1.0)

    # Architect (prefer /health if you added it, otherwise /openapi.json is fine)
    try:
        architect_port = int(ARCHITECT_URL.rsplit(":", 1)[-1])
    except Exception:
        architect_port = 8012

    architect_health = f"http://localhost:{architect_port}/health"
    architect_ok, architect_detail = _check_http_ok(architect_health, timeout_s=1.0)

    if not architect_ok:
        # fallback if architect has no /health yet
        architect_openapi = f"http://localhost:{architect_port}/openapi.json"
        architect_ok2, architect_detail2 = _check_http_ok(architect_openapi, timeout_s=1.0)
        if architect_ok2:
            architect_ok, architect_detail = True, None
        else:
            architect_ok, architect_detail = False, (architect_detail or architect_detail2)

    return [
        {"name": "teacher_council", "port": teacher_port, "ok": teacher_ok, "detail": teacher_detail},
        {"name": "orchestrator", "port": orch_port, "ok": orch_ok, "detail": orch_detail},
        {"name": "architect_council", "port": architect_port, "ok": architect_ok, "detail": architect_detail},
    ]

def run_forever() -> None:
    backoff = OPS_REPORT_INTERVAL_S
    while True:
        try:
            cpu_pct = psutil.cpu_percent(interval=None)
            ram_pct = psutil.virtual_memory().percent
            disk_pct = psutil.disk_usage("/").percent
            try:
                load_1m = os.getloadavg()[0]
            except Exception:
                load_1m = None

            payload = {
                "node_id": ORCHESTRATOR_NODE_NAME,  # always use orchestrator node name
                "cpu_pct": float(cpu_pct),
                "ram_pct": float(ram_pct),
                "disk_pct": float(disk_pct),
                "load_1m": float(load_1m) if load_1m is not None else None,
                "services": build_services(),
                "counters": {},
            }

            r = SESSION.post(f"{OPS_BOB_URL}/ops/report", json=payload, timeout=OPS_REPORT_TIMEOUT_S)
            r.raise_for_status()
            backoff = OPS_REPORT_INTERVAL_S
        except Exception:
            backoff = min(40.0, max(OPS_REPORT_INTERVAL_S, backoff * 2))

        time.sleep(backoff)
