import os
import time
import logging
from typing import Any, Dict, List, Optional, Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

log = logging.getLogger("reflector_service")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

app = FastAPI(
    title="Bobiverse Reflector v1",
    version="1.0.0",
)

# ----------------------------
# Import reflector brain
# ----------------------------
try:
    from tools.scripts import reflector_brain  # type: ignore
except Exception as e:
    reflector_brain = None
    log.exception("Failed to import tools.scripts.reflector_brain: %s", e)


# ----------------------------
# Helpers: resolve a function from reflector_brain
# ----------------------------
def _pick_fn(names: List[str]) -> Optional[Callable[..., Any]]:
    if reflector_brain is None:
        return None
    for n in names:
        fn = getattr(reflector_brain, n, None)
        if callable(fn):
            return fn
    return None


# ----------------------------
# Request models
# ----------------------------
class ReflectorRunRequest(BaseModel):
    module: Optional[str] = None
    limit: int = 200


# ----------------------------
# Endpoints
# ----------------------------
@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "reflector_service",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "brain_import_ok": reflector_brain is not None,
    }


@app.get("/reflector/insights")
def reflector_insights(limit_failures: int = 10) -> Dict[str, Any]:
    """
    CLI expects:
      GET /reflector/insights?limit_failures=10

    Returns a dict containing:
      summary, worst_nodes, worst_modules, top_error_types, recent_failures
    """
    fn = _pick_fn([
        "get_insights",
        "reflector_insights",
        "compute_insights",
        "build_insights",
        "insights",
    ])
    if fn is None:
        raise HTTPException(
            status_code=500,
            detail="No insights function found in reflector_brain.py. Expected one of: "
                   "get_insights / reflector_insights / compute_insights / build_insights / insights",
        )

    try:
        # Try keyword first (most likely)
        try:
            data = fn(limit_failures=limit_failures)
        except TypeError:
            # Fall back to positional
            data = fn(limit_failures)
    except Exception as e:
        log.exception("reflector_insights failed")
        raise HTTPException(status_code=500, detail=str(e))

    # Basic sanity check to help your CLI not crash with KeyError
    required = ["summary", "worst_nodes", "worst_modules", "top_error_types", "recent_failures"]
    missing = [k for k in required if k not in (data or {})]
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Reflector insights returned missing keys: {missing}. "
                   f"Got keys={list((data or {}).keys())}",
        )

    return data


@app.post("/reflector/run")
def reflector_run(req: ReflectorRunRequest) -> Dict[str, Any]:
    """
    reflector_run_cli expects:
      POST /reflector/run  { module, limit }

    Returns (expected by your CLI):
    {
      "status": "ok",
      "module": <str|null>,
      "limit": <int>,
      "execution_id": <int|optional>,
      "task_uuid": <str|optional>,
      "summary": <str>,
      "lessons_created": <int>,
      "proposals_created": <int>,
    }
    """
    fn = _pick_fn([
        "run_reflector",
        "reflector_run",
        "run",
        "run_once",
    ])
    if fn is None:
        raise HTTPException(
            status_code=500,
            detail="No run function found in reflector_brain.py. Expected one of: "
                   "run_reflector / reflector_run / run / run_once",
        )

    try:
        # Prefer keyword call
        try:
            result = fn(module=req.module, limit=req.limit)
        except TypeError:
            # Fall back to positional
            result = fn(req.module, req.limit)
    except Exception as e:
        log.exception("reflector_run failed")
        raise HTTPException(status_code=500, detail=str(e))

    # If brain returns nothing or non-dict, normalize
    if result is None:
        result = {}

    if not isinstance(result, dict):
        # If it returns a tuple etc., coerce to string summary
        result = {"summary": str(result)}

    # Normalize into the CLI-expected fields
    normalized = {
        "status": result.get("status", "ok"),
        "module": result.get("module", req.module),
        "limit": result.get("limit", req.limit),
        "execution_id": result.get("execution_id"),
        "task_uuid": result.get("task_uuid"),
        "summary": result.get("summary") or result.get("message") or "Reflector run complete.",
        "lessons_created": result.get("lessons_created", result.get("lessons", 0)),
        "proposals_created": result.get("proposals_created", result.get("proposals", 0)),
    }
    return normalized


@app.get("/reflector/lessons")
def reflector_lessons(limit: int = 50) -> Dict[str, Any]:
    fn = _pick_fn(["get_lessons", "reflector_lessons", "lessons"])
    if fn is None:
        raise HTTPException(status_code=500, detail="No lessons function found in reflector_brain.py.")
    try:
        try:
            rows = fn(limit=limit)
        except TypeError:
            rows = fn(limit)
    except Exception as e:
        log.exception("reflector_lessons failed")
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "limit": limit, "lessons": rows}


@app.get("/reflector/proposals")
def reflector_proposals(limit: int = 50) -> Dict[str, Any]:
    fn = _pick_fn(["get_proposals", "reflector_proposals", "proposals"])
    if fn is None:
        raise HTTPException(status_code=500, detail="No proposals function found in reflector_brain.py.")
    try:
        try:
            rows = fn(limit=limit)
        except TypeError:
            rows = fn(limit)
    except Exception as e:
        log.exception("reflector_proposals failed")
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "limit": limit, "proposals": rows}
