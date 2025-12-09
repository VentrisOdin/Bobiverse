import os
import time
import socket
import asyncio
import traceback
from pathlib import Path
import sys
from typing import Dict, Optional, Any
import logging

import psutil
import requests
from dotenv import load_dotenv

logger = logging.getLogger("node_agent")

# Add councils to Python path so we can import the dev council client
COUNCILS_PATH = Path.home() / "bobiverse" / "councils"
sys.path.append(str(COUNCILS_PATH))

from dev_council.dev_council_client import analyse_dev_task_async  # type: ignore

load_dotenv()

# =========================
#    Configuration
# =========================

AGENT_VERSION = "bob-agent-v1"

NODE_NAME = os.getenv("BOBIVERSE_NODE_NAME", "data-mainpc")
NODE_ROLE = os.getenv("NODE_ROLE", "worker")

# If not set, we'll auto-detect below. IMPORTANT: default must be empty string.
TAILSCALE_IP = os.getenv("TAILSCALE_IP", "").strip()

ORCH_URL = os.getenv("ORCHESTRATOR_URL", "http://100.111.201.26:5080").rstrip("/")
DEV_COUNCIL_URL = os.getenv("DEV_COUNCIL_URL", "http://localhost:8011")
HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL_SEC", 5))

# Reuse a single HTTP session for efficiency
SESSION = requests.Session()


# =========================
#    Helper Functions
# =========================

def get_tailscale_ip() -> str:
    """
    Returns the node's Tailscale IP from .env if provided,
    otherwise attempts automatic detection.
    """
    if TAILSCALE_IP:
        return TAILSCALE_IP

    # Fallback auto-detect of primary outbound IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def get_node_metrics() -> Dict[str, Any]:
    """Collects simple metrics for heartbeats."""
    load = psutil.cpu_percent(interval=None) / 100.0
    free_mem = psutil.virtual_memory().available // (1024 * 1024)
    return {
        "load": load,
        "free_memory_mb": free_mem,
    }


# =========================
#     Core Actions
# =========================

def process_one_dev_task() -> None:
    """
    One full Dev Council loop:

    1) Ask orchestrator for next dev task (/dev/tasks/next).
    2) If none, return.
    3) Call Dev Council on localhost with a DevTaskRequest-shaped payload.
    4) Report result back to orchestrator (/dev/tasks/{task_uuid}/result).
    """

    # 1) Ask Prime Bob for the next dev task
    try:
        resp = requests.get(
            f"{ORCH_URL}/dev/tasks/next",
            params={"node_name": NODE_NAME},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logging.error("[DEV_TASK] Error calling /dev/tasks/next: %s", e)
        return

    # If no dev tasks pending, FastAPI returns JSON null -> resp.json() is None
    dev_task = resp.json()
    if not dev_task:
        # No dev work right now
        return

    task_uuid = dev_task["task_uuid"]
    execution_id = dev_task["execution_id"]
    input_payload = dev_task.get("input_payload") or {}

    logging.info(
        "[DEV_TASK] Received dev task uuid=%s exec_id=%s from %s",
        task_uuid,
        execution_id,
        ORCH_URL,
    )

    # ---- Build a proper DevTaskRequest payload for Dev Council ----
    # Derive a decent user_prompt from the original payload.
    # IMPORTANT: do NOT fall back to 'details' here, because for bobctl dev
    # 'details' is a big JSON string, not a human prompt.
    description = (
        input_payload.get("description")
        or f"Dev task {task_uuid} from orchestrator."
    )

    # Context for Dev Council.
    # For v1.1 we don't hard-wire any local files here; the real code context
    # comes from the 'details' payload created by bobctl dev.
    context_files: Dict[str, str] = {}

    # Let Dev Council's own prompt template handle "You are Dev Bob" etc.
    user_prompt = description

    dev_council_request = {
        "user_prompt": user_prompt,
        "context_files": context_files,
        "task_id": str(task_uuid),
        "task_type": "dev",
        # Forward bobctl dev JSON (if any) so Dev Council can see it
        "details": input_payload.get("details"),
    }

    # 2) Call Dev Council on this node
    try:
        dc_resp = requests.post(
            f"{DEV_COUNCIL_URL}/dev_council/analyse",
            json=dev_council_request,
            timeout=120,
        )
        dc_resp.raise_for_status()
        dev_result = dc_resp.json()

        # Prefer structured summary if present
        summary = (
            dev_result.get("analysis", {}).get("summary")
            if isinstance(dev_result, dict) and "analysis" in dev_result
            else "Dev Council completed successfully."
        )
        status = "success"

        logging.info(
            "[DEV_TASK] Dev Council success for uuid=%s: %s",
            task_uuid,
            summary,
        )
    except Exception as e:
        # If ANYTHING goes wrong (request, JSON, type errors, etc.), mark failed
        status = "failed"
        summary = f"Dev Council error: {e}"
        dev_result = {"error": str(e)}
        logging.error(
            "[DEV_TASK] Error calling Dev Council service for uuid=%s: %s",
            task_uuid,
            e,
        )

    # 3) Report result back to orchestrator
    body = {
        "execution_id": execution_id,
        "status": status,            # "success" | "partial" | "failed"
        "output_summary": summary,   # goes into task_executions.output_summary
        "full_response": dev_result, # stored as metrics_json
    }

    try:
        result_resp = requests.post(
            f"{ORCH_URL}/dev/tasks/{task_uuid}/result",
            json=body,
            timeout=20,
        )
        result_resp.raise_for_status()
        logging.info(
            "[DEV_TASK] Reported result for uuid=%s with status=%s",
            task_uuid,
            status,
        )
    except requests.RequestException as e:
        logging.error(
            "[DEV_TASK] Failed to report dev result for uuid=%s: %s",
            task_uuid,
            e,
        )


async def handle_dev_task(task) -> Dict[str, Any]:
    """
    Handle software development tasks using Dev Council (DeepSeek).
    Returns a dict shaped for TaskResult (minus node_name, which is added later).
    """
    try:
        payload = getattr(task, "input_payload", None) or {}

        # Prefer structured description, fall back to raw task.description
        description = payload.get("description") or getattr(task, "description", "") or ""
        code_snippet = payload.get("code_snippet")
        repo_context = payload.get("repo_context")
        extra_instructions = payload.get("extra_instructions")

        # Call Dev Council
        result = await analyse_dev_task_async(
            task_type=getattr(task, "high_level_type", "dev"),
            description=description,
            code_snippet=code_snippet,
            repo_context=repo_context,
            extra_instructions=extra_instructions,
            task_id=getattr(task, "task_uuid", None),
        )

        summary = result.analysis.summary

        # Return ONLY what TaskResult cares about (node_name is added later)
        return {
            "status": "completed",   # must be 'completed' or 'failed'
            "result": summary
        }

    except Exception as e:
        # Still match TaskResult shape
        return {
            "status": "failed",
            "result": f"Dev task failed: {e}"
        }


def register_node() -> bool:
    """Send registration payload to Prime Bob."""
    print(f"[NODE_AGENT {AGENT_VERSION}] Registering node '{NODE_NAME}' with Prime Bob...")

    payload = {
        "name": NODE_NAME,
        "role": NODE_ROLE,
        "tailscale_ip": get_tailscale_ip(),
        "capabilities": ["shell", "python", "dev"],
    }

    try:
        resp = SESSION.post(
            f"{ORCH_URL}/register",
            json=payload,
            timeout=5,
        )
        resp.raise_for_status()
        print(f"[NODE_AGENT] Registration OK for '{NODE_NAME}': {resp.status_code}")
        return True
    except requests.exceptions.RequestException as e:
        print(f"[NODE_AGENT] Registration failed for '{NODE_NAME}': {e}")
        return False


def send_heartbeat() -> None:
    """Send periodic heartbeat to Prime Bob."""
    metrics = get_node_metrics()

    active = []

    # We know this node supports dev tasks
    if "dev" in NODE_ROLE or "dev" in os.getenv("NODE_CAPABILITIES", ""):
        active.append("dev")

    # Or just hardcode for now, since dev council is always running:
    active.append("dev")

    payload = {
        "name": NODE_NAME,
        "load": metrics["load"],
        "free_memory_mb": metrics["free_memory_mb"],
        "active_councils": active,
    }

    try:
        resp = SESSION.post(
            f"{ORCH_URL}/heartbeat",
            json=payload,
            timeout=5,
        )
        resp.raise_for_status()
        print(
            f"[NODE_AGENT] Heartbeat OK for '{NODE_NAME}': "
            f"load={metrics['load']:.2f}, free={metrics['free_memory_mb']}MB"
        )
    except requests.exceptions.RequestException as e:
        print(f"[NODE_AGENT] Heartbeat failed for '{NODE_NAME}': {e}")


def _extract_task_from_response(data: Any) -> Optional[Dict[str, Any]]:
    """
    Make the agent tolerant of different response shapes from /tasks/next.

    Supported shapes:
    - {} or None -> no task
    - { "id": ..., "description": ... } -> direct task object
    - { "task": { ... } } -> wrapped task
    """
    if not data:
        return None

    # 1) Wrapped: {"task": {...}}
    if isinstance(data, dict) and "task" in data:
        task = data["task"]
        if task:
            return task
        return None

    # 2) Direct task object with "id"
    if isinstance(data, dict) and "id" in data:
        return data

    # 3) List of tasks: take first one (simple behaviour for v1)
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict) and "id" in first:
            return first

    # Otherwise, we don't know what this is yet
    print(f"[NODE_AGENT] Warning: Unrecognised task response shape: {data}")
    return None


async def poll_for_task() -> None:
    """Ask Prime Bob if there is a pending task for this node."""
    try:
        resp = SESSION.get(
            f"{ORCH_URL}/tasks/next",
            params={"node_name": NODE_NAME},
            timeout=5,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[NODE_AGENT] Task poll error for '{NODE_NAME}': {e}")
        return

    try:
        data = resp.json()
    except ValueError as e:
        print(f"[NODE_AGENT] Task poll JSON decode error for '{NODE_NAME}': {e}")
        return

    task = _extract_task_from_response(data)
    if not task:
        # No task available for this node
        return

    # Extract task info
    task_id = task.get("id")
    desc = task.get("description", "<no description>")

    if task_id is None:
        print(f"[NODE_AGENT] Received malformed task for '{NODE_NAME}': {task}")
        return

    print(f"[NODE_AGENT] '{NODE_NAME}' received task id={task_id}: {desc}")

    # Create a simple task object wrapper
    class TaskWrapper:
        def __init__(self, task_dict):
            self.task_uuid = task_dict.get("id")
            # If missing, treat as dev for now
            self.high_level_type = task_dict.get("high_level_type") or "dev"
            self.input_payload = task_dict.get("input_payload", {})
            self.description = task_dict.get("description", "")

    task_obj = TaskWrapper(task)

    # Route to appropriate handler based on task type
    if task_obj.high_level_type == "dev":
        result = await handle_dev_task(task_obj)
    else:
        # Default: fake execution for other task types
        result = {
            "status": "completed",
            "result": f"Fake execution complete on {NODE_NAME}",
        }

    result_payload = {
        "node_name": NODE_NAME,
        **result,
    }

    try:
        resp2 = SESSION.post(
            f"{ORCH_URL}/tasks/{task_id}/result",
            json=result_payload,
            timeout=5,
        )
        resp2.raise_for_status()
        print(f"[NODE_AGENT] Reported completion for task id={task_id} from '{NODE_NAME}'")
    except Exception as e:
        print(f"[NODE_AGENT] Error reporting result for task {task_id} from '{NODE_NAME}': {e}")


# =========================
#        Main Loop
# =========================

def main() -> None:
    if not ORCH_URL:
        logging.error("[NODE_AGENT] CRITICAL: ORCHESTRATOR_URL not set. Cannot start.")
        return

    logging.info("[NODE_AGENT] Starting node agent for %s", NODE_NAME)
    logging.info(
        "[NODE_AGENT] Version %s, Role: %s, Orchestrator: %s",
        AGENT_VERSION,
        NODE_ROLE,
        ORCH_URL,
    )

    # Initial registration with simple retry
    if not register_node():
        logging.warning("[NODE_AGENT] Initial registration failed. Retrying in 10 seconds...")
        time.sleep(10)
        if not register_node():
            logging.error("[NODE_AGENT] CRITICAL: Could not connect to Prime Bob. Exiting.")
            return

    # Main loop
    while True:
        try:
            # Regular heartbeat
            send_heartbeat()

            # Generic task processing (if you have it)
            # process_one_generic_task()

            # New: Dev Council pipeline
            process_one_dev_task()

        except Exception as e:
            logging.exception("[NODE_AGENT] Unexpected error in main loop: %s", e)

        time.sleep(3)


if __name__ == "__main__":
    main()
