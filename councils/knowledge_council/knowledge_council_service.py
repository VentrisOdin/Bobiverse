# ~/bobiverse/councils/knowledge_council/knowledge_council_service.py

import os
import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import httpx

from councils.knowledge_council.schemas import (
    KnowledgeTaskRequest,
    KnowledgeTaskResponse,
    KnowledgeTaskAnalysis,
)

# ---------------- Env & Logging ---------------- #

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

KNOWLEDGE_COUNCIL_NAME = os.getenv("KNOWLEDGE_COUNCIL_NAME", "knowledge_council_v1")
KNOWLEDGE_COUNCIL_MODEL = os.getenv("KNOWLEDGE_COUNCIL_MODEL", "llama3:8b")

# Single source of truth for Ollama URL, shared with Architect Bob.
# Prefer OLLAMA_URL (Architect style), fall back to OLLAMA_BASE_URL, then default.
OLLAMA_URL = (
    os.getenv("OLLAMA_URL")
    or os.getenv("OLLAMA_BASE_URL")
    or "http://localhost:11434"
)

logger = logging.getLogger("knowledge_council")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

logger.info(
    f"[KnowledgeCouncil] Starting with model={KNOWLEDGE_COUNCIL_MODEL}, "
    f"OLLAMA_URL={OLLAMA_URL}"
)

# ---------------- FastAPI App ---------------- #

app = FastAPI(
    title="Knowledge Council Service",
    description="Knowledge Bob – concept explainer and QA service.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten later if needed
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- System Prompt ---------------- #

SYSTEM_PROMPT = """
You are Knowledge Bob, a member of the Bobiverse Knowledge Council.

Your job:
- Explain concepts clearly and accurately.
- Use ANY extra_context provided as helpful background, but do not assume it is always correct.
- If the question is unclear, state assumptions.
- Suggest helpful follow-up questions or next steps.

You MUST respond with a single JSON object ONLY, no extra text, no markdown.
The JSON MUST have exactly these keys:
- "answer": string – the direct answer or explanation, in clear language.
- "reasoning": string – step-by-step reasoning or supporting explanation.
- "followups": array of strings – suggested follow-up questions or topics.

If you are about to write anything that is not part of the JSON object, STOP and only output the JSON object.

Example (structure only):
{
  "answer": "Short answer here...",
  "reasoning": "Longer explanation here...",
  "followups": [
    "Follow-up question 1",
    "Follow-up question 2"
  ]
}
""".strip()


# ---------------- Helpers ---------------- #

def extract_json_block(text: str) -> str:
    """
    Extract the JSON object from the model output.
    Handles cases where the model wraps it in markdown or extra text.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output")
    return text[start : end + 1]


async def call_ollama_knowledge(payload: Dict[str, Any]) -> str:
    """
    Call Ollama /api/chat and return the message content as a string.
    This mirrors Architect Bob's usage pattern.
    """
    url = f"{OLLAMA_URL.rstrip('/')}/api/chat"
    logger.info(
        f"[KnowledgeCouncil] Calling Ollama chat endpoint at {url} "
        f"with model={KNOWLEDGE_COUNCIL_MODEL}"
    )
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                f"[KnowledgeCouncil] Ollama HTTP error: "
                f"{e.response.status_code} {e.response.text[:200]}"
            )
            raise HTTPException(
                status_code=502,
                detail=f"Ollama error {e.response.status_code}: "
                       f"{e.response.text[:200]}",
            )

        try:
            data = resp.json()
            message = data["message"]
            content = message["content"]
        except Exception as e:
            logger.error(f"[KnowledgeCouncil] Unexpected Ollama format: {e}")
            raise HTTPException(
                status_code=502,
                detail=f"Unexpected Ollama format: {e}",
            )

        if not content:
            raise HTTPException(
                status_code=500,
                detail="Ollama /api/chat returned empty content",
            )

        return content


# ---------------- Routes ---------------- #

@app.get("/health")
async def health():
    """
    Simple health check for Knowledge Bob.
    Matches Architect's style so monitor can treat them similarly.
    """
    return {
        "status": "ok",
        "council": KNOWLEDGE_COUNCIL_NAME,
        "model": KNOWLEDGE_COUNCIL_MODEL,
        "ollama_url": OLLAMA_URL,
    }


@app.post("/knowledge/analyse", response_model=KnowledgeTaskResponse)
async def analyse_knowledge(request: KnowledgeTaskRequest):
    """
    Main Knowledge Bob endpoint.
    Accepts a question + optional extra_context, calls Llama via Ollama,
    and returns structured analysis.
    """
    user_prompt_parts = [
        "You are answering a knowledge / explanation question.",
        f"QUESTION:\n{request.question}",
    ]

    if request.extra_context:
        user_prompt_parts.append(
            "EXTRA CONTEXT (may or may not be fully correct, use with judgement):\n"
            f"{request.extra_context}"
        )

    user_prompt_parts.append(
        "Remember: respond ONLY with a JSON object matching the required schema."
    )

    user_prompt = "\n\n".join(user_prompt_parts)

    payload = {
        "model": KNOWLEDGE_COUNCIL_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        # Optional: you can add options like temperature here if you want
        # "options": {"temperature": 0.2},
    }

    try:
        raw_output = await call_ollama_knowledge(payload)
        logger.info(
            f"[{request.task_id}] Ollama raw output (truncated): {raw_output[:300]}"
        )

        json_str = extract_json_block(raw_output)
        parsed = json.loads(json_str)

        analysis = KnowledgeTaskAnalysis(
            answer=parsed.get("answer", "").strip(),
            reasoning=parsed.get("reasoning", "").strip(),
            followups=[str(f).strip() for f in parsed.get("followups", [])],
        )

    except Exception as e:
        logger.error(f"[{request.task_id}] Error parsing Knowledge Bob output: {e}")
        # Fallback: return whatever we got in a safe wrapper
        analysis = KnowledgeTaskAnalysis(
            answer="Knowledge Bob could not produce a clean JSON answer.",
            reasoning=f"Parsing error: {e}. See raw_output for details.",
            followups=[],
        )
        raw_output = raw_output if "raw_output" in locals() else str(e)

    response = KnowledgeTaskResponse(
        task_id=request.task_id,
        task_type=request.task_type,
        model=KNOWLEDGE_COUNCIL_MODEL,
        raw_output=raw_output,
        analysis=analysis,
    )

    return response
