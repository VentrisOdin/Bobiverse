import os
import json
import logging
from typing import Optional, Dict, Any

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("architect_council")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Architect Council Service (Server-side)",
    version="1.0.0",
)

ARCHITECT_LLM_URL = os.getenv("ARCHITECT_LLM_URL")
MODEL_NAME = os.getenv("ARCHITECT_MODEL_NAME", "architect-bob-llm")


class ArchitectRequest(BaseModel):
    insights: dict
    latest_lesson_id: Optional[int] = None


class ArchitectProposal(BaseModel):
    proposal_uuid: str
    proposal_type: str
    target_module: str
    motivation_lesson_id: Optional[int] = None
    risk_score: int
    description: str
    action_payload: Dict[str, Any]
    source: str = "llm-architect-bob"


class ArchitectResponse(BaseModel):
    proposal: ArchitectProposal


def build_architect_prompt(insights: dict, latest_lesson_id: Optional[int]) -> str:
    """
    Build the LLM prompt for Architect Bob.
    This is where you encode the “how to think about insights” logic.
    """
    body = {
        "insights": insights,
        "latest_lesson_id": latest_lesson_id,
        "instructions": (
            "You are Architect Bob, the Reflector Brain of the Bobiverse. "
            "You receive telemetry and must propose a SMALL, SAFE improvement.\n\n"
            "Return ONLY a JSON object with the following schema:\n"
            "{\n"
            '  "proposal_uuid": "string-uuid",\n'
            '  "proposal_type": "PROMPT_TWEAK | ROUTING_POLICY | MODULE_ISOLATION | EXPERIMENT",\n'
            '  "target_module": "dev_council | knowledge_council | etc",\n'
            '  "motivation_lesson_id": null or integer,\n'
            '  "risk_score": 1-5,\n'
            '  "description": "short summary",\n'
            '  "action_payload": { "key": "...", "new_value": "..." },\n'
            '  "source": "llm-architect-bob"\n'
            "}\n"
            "No extra commentary, no markdown, just JSON.\n"
        ),
    }
    # Many backends like to see a JSON payload, but if yours wants a plain text prompt,
    # you can change this to json.dumps(body) here instead.
    return json.dumps(body, indent=2)


def call_architect_llm(prompt: str) -> str:
    """
    Call the Architect LLM backend on the MAIN PC.

    Adjust this to match your existing API (Ollama, custom FastAPI, etc.).
    For now we assume it accepts JSON {prompt, model} and returns {response: "..."}.
    """
    if not ARCHITECT_LLM_URL:
        raise RuntimeError("ARCHITECT_LLM_URL is not set in .env")

    logger.info("Calling Architect LLM at %s", ARCHITECT_LLM_URL)

    # EXAMPLE shape – change to match your real LLM API
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
    }

    resp = requests.post(ARCHITECT_LLM_URL, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    # If your LLM returns a different field, change this:
    raw = data.get("response") or data.get("output") or data.get("text")
    if not raw:
        raise RuntimeError(f"Architect LLM returned no 'response' text. Raw: {data}")
    return raw


@app.post("/architect/propose", response_model=ArchitectResponse)
async def architect_propose(payload: ArchitectRequest):
    """
    This runs on the SERVER.
    It builds a prompt, calls the Architect LLM on the MAIN PC,
    parses JSON, and returns a clean proposal object for Reflector Brain.
    """
    try:
        prompt = build_architect_prompt(payload.insights, payload.latest_lesson_id)
        raw_output = call_architect_llm(prompt)

        try:
            proposal_data = json.loads(raw_output)
        except json.JSONDecodeError as e:
            logger.error("Architect LLM invalid JSON: %s\nRaw: %s", e, raw_output)
            raise HTTPException(status_code=500, detail="Invalid JSON from Architect LLM")

        proposal = ArchitectProposal(
            proposal_uuid=proposal_data.get("proposal_uuid"),
            proposal_type=proposal_data.get("proposal_type"),
            target_module=proposal_data.get("target_module"),
            motivation_lesson_id=proposal_data.get("motivation_lesson_id"),
            risk_score=int(proposal_data.get("risk_score")),
            description=proposal_data.get("description"),
            action_payload=proposal_data.get("action_payload"),
            source=proposal_data.get("source", "llm-architect-bob"),
        )

        return ArchitectResponse(proposal=proposal)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Architect propose failed")
        raise HTTPException(status_code=500, detail=str(e))



# Health check endpoint
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "architect_council",
        "llm_url": ARCHITECT_LLM_URL,
        "model": MODEL_NAME,
    }

# Dev-only run
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("ARCHITECT_HOST", "0.0.0.0")
    port = int(os.getenv("ARCHITECT_PORT", "8012"))
    uvicorn.run("architect_council_service:app", host=host, port=port, reload=True)
