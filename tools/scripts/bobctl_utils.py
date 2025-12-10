# tools/scripts/bobctl_utils.py

import base64
import io
import os
import tarfile
from typing import Any, Dict, List, Optional

import sys
import json
import requests

# Default orchestrator URL – override with env or --orch-url
DEFAULT_ORCH_URL = os.environ.get(
    "BOBIVERSE_ORCH_URL",
    "http://100.111.201.26:5080",
)


# -----------------------------
# Payload builders
# -----------------------------

def prepare_single_file_payload(file_path: str, instructions: str) -> Dict[str, Any]:
    """
    Reads a single file and structures the Dev Task payload.
    """
    if not os.path.isfile(file_path):
        raise ValueError(f"File not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        code_content = f.read()

    return {
        "mode": "single_file",
        "filename": os.path.basename(file_path),
        "instructions": instructions,
        "code": code_content,
    }


def prepare_stdin_payload(instructions: str) -> Dict[str, Any]:
    """
    Reads from standard input and structures the Dev Task payload.
    """
    code_content = sys.stdin.read()
    if not code_content.strip():
        raise ValueError("No input provided via stdin.")

    return {
        "mode": "stdin_blob",
        "filename": "stdin_blob",
        "instructions": instructions,
        "code": code_content,
    }


def prepare_directory_payload(dir_path: str, instructions: str) -> Dict[str, Any]:
    """
    Compresses a directory into a base64 tar.gz archive.
    Filters out hidden files, venvs, __pycache__, .git, node_modules, etc.
    """
    if not os.path.isdir(dir_path):
        raise ValueError(f"Directory not found: {dir_path}")

    manifest: List[str] = []
    tar_buffer = io.BytesIO()

    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
        for root, _, files in os.walk(dir_path):
            for file in files:
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, dir_path)

                parts = arcname.split(os.sep)
                if any(
                    p.startswith(".")
                    or p in ("__pycache__", "venv", ".venv", ".git", "node_modules")
                    for p in parts
                ):
                    continue

                tar.add(full_path, arcname=arcname)
                manifest.append(arcname)

    tar_buffer.seek(0)
    archive_b64 = base64.b64encode(tar_buffer.read()).decode("utf-8")

    return {
        "mode": "directory",
        "directory": os.path.basename(dir_path),
        "file_manifest": manifest,
        "instructions": instructions,
        "archive_b64": archive_b64,
    }


# -----------------------------
# Orchestrator submit helper
# -----------------------------

def submit_dev_task_to_orchestrator(
    payload: Dict[str, Any],
    instructions: str,
    orch_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Submit a Dev task to the orchestrator.

    This mirrors scripts/submit_dev.py so we don't have to
    change the orchestrator right now.

    - POST {orch_url}/tasks/dev
    - Body fields: description, details, submitted_by, priority
    - We encode the rich Dev payload as JSON in 'details'.
    """
    base_url = orch_url or DEFAULT_ORCH_URL
    url = f"{base_url.rstrip('/')}/tasks/dev"

    body = {
        "description": instructions,
        # Encode our full Dev Bob payload as JSON text in 'details'
        "details": json.dumps(payload),
        "submitted_by": "bobctl-dev",
        "priority": "normal",
    }

    print(f"[bobctl-dev] POST {url}")
    # Optional: uncomment if you want to see the full payload:
    # print(f"[bobctl-dev] Body: {json.dumps(body, indent=2)}")

    resp = requests.post(url, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()
