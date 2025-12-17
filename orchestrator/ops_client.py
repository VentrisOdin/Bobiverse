import os
import requests
import logging
from typing import Dict, Any, List

logger = logging.getLogger("orchestrator.ops_client")

OPS_BOB_URL = os.getenv("OPS_BOB_URL", "http://100.111.201.26:8014").rstrip("/")
OPS_HINTS_TIMEOUT_S = float(os.getenv("OPS_HINTS_TIMEOUT_S", "0.5"))

def get_routing_hints() -> List[Dict[str, Any]]:
    try:
        r = requests.get(f"{OPS_BOB_URL}/ops/routing/hints", timeout=OPS_HINTS_TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.warning(f"[ops_client] routing_hints unavailable: {e}")
        return []

def get_ops_hints() -> Dict[str, Dict[str, Any]]:
    """
    Adapter: return node_id -> hint dict.
    Keeps main.py clean and gives O(1) lookup by node name.
    """
    hints_list = get_routing_hints()
    return {
        h.get("node_id"): h
        for h in hints_list
        if isinstance(h, dict) and h.get("node_id")
    }
