import os
import json
import textwrap
import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
from dotenv import load_dotenv
from pydantic import ValidationError

logger = logging.getLogger("dev_council")

from .schemas import (
    DevTaskRequest,
    DevTaskResponse,
    DevTaskAnalysis,
    SuggestedChange,
    CodeSnippet,
)

# Load .env from this folder
load_dotenv()

DEV_COUNCIL_NAME = os.getenv("DEV_COUNCIL_NAME", "dev_council_v1")
DEV_COUNCIL_MODEL = os.getenv("DEV_COUNCIL_MODEL", "deepseek-coder:6.7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

app = FastAPI(
    title="Bobiverse Dev Council",
    description="Dev Council microservice powered by DeepSeek via Ollama.",
    version="0.1.0",
)

# Basic CORS (we can lock this down later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def call_deepseek(prompt: str, model: Optional[str] = None) -> str:
    """
    Call DeepSeek via the Ollama HTTP API and return the generated text.
    """
    model_name = model or DEV_COUNCIL_MODEL
    url = f"{OLLAMA_BASE_URL}/api/generate"

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        # Ask Ollama to enforce valid JSON output
        "format": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Error calling DeepSeek via Ollama: {e}"
        )

    text = data.get("response")
    if not text:
        raise HTTPException(
            status_code=500,
            detail="DeepSeek returned an empty response"
        )

    return text


DEV_PROMPT_TEMPLATE = """
You are Dev Bob, a surgical code-modification assistant for the Bobiverse project.

You MUST obey these rules:

1. You ONLY work with the files and code provided in the CONTEXT below.
2. You MUST NOT invent new file paths, new types, or new functions unless
   explicitly requested. Prefer modifying existing code.
3. Any change you propose MUST:
   - Reference an existing file from the CONTEXT.
   - Include `before_code` that is an EXACT copy-paste from the CONTEXT.
   - Include `after_code` that is a minimal, correct modification.
4. If you are unsure about existing types or names, you MUST inspect the CONTEXT;
   do not guess.
5. You MUST NOT use FastAPI's `Depends` or other constructs unless they already
   appear in the provided code.

TASK
-----
{task_description}

CONTEXT FILES
-------------
Below are the available files. You may ONLY reference these files.

{context_blocks}

OUTPUT FORMAT (JSON ONLY)
-------------------------
You MUST output a single JSON object with this exact structure:

{{
  "summary": "...",
  "reasoning": "...",
  "suggested_changes": [
    {{
      "id": "change_1",
      "title": "...",
      "description": "...",
      "complexity": 2,
      "snippets": [
        {{
          "file": "orchestrator/main.py",
          "description": "what this snippet is about",
          "before_code": "EXACT code from the context",
          "after_code": "the modified code"
        }}
      ]
    }}
  ],
  "example_code": "optional extra code sample",
  "tests_suggested": [
    "test case description"
  ],
  "risks": {{
    "complexity": 1,
    "behavior_risks": [
      "..."
    ],
    "notes": "..."
  }}
}}

HARD REQUIREMENTS FOR OUTPUT:
- You MUST output a single JSON object that matches the fields described above
  (summary, reasoning, suggested_changes, tests_suggested, risks, etc.).
- Your FIRST character MUST be an opening brace {{.
- Your LAST character MUST be a closing brace }}.
- Do NOT include markdown, backticks, comments, or any extra text before or after the JSON.
- Do NOT say "here is your JSON" or wrap the JSON in ``` fences.
- All strings must use double quotes, and there must be NO trailing commas.
""".strip()


def build_context_blocks(context_files: dict) -> str:
    """
    Build context blocks from context_files dict.
    You can truncate very large files if needed.
    """
    blocks = []
    for path, content in context_files.items():
        blocks.append(
            f"### FILE: {path}\n"
            f"{content}\n"
        )
    return "\n\n".join(blocks)


def validate_suggested_changes(
    analysis: DevTaskAnalysis,
    context_files: dict
) -> DevTaskAnalysis:
    """
    Validate that suggested changes reference real files and contain
    exact before_code snippets from the provided context.

    If validation fails, we drop suggested_changes but do NOT raise,
    so the pipeline stays green.
    """
    errors = []

    for change in analysis.suggested_changes:
        for snip in change.snippets:
            if snip.file not in context_files:
                errors.append(f"Snippet references unknown file: {snip.file}")
                continue

            content = context_files[snip.file]
            if snip.before_code not in content:
                errors.append(
                    f"before_code for snippet {change.id} not found in {snip.file}"
                )

    if errors:
        logger.warning(
            "Dev Council suggestions failed validation; dropping all suggested_changes. Errors: %s",
            errors,
        )
        analysis.suggested_changes = []

    return analysis


async def run_dev_analysis(req: DevTaskRequest) -> DevTaskResponse:
    """
    Main Dev Council analysis logic with a small retry loop for JSON stability.
    """
    context_blocks = build_context_blocks(req.context_files)

    MAX_RETRIES = 2  # Max 3 attempts total (0,1,2)
    raw_output = ""
    last_error = None
    analysis = None

    for attempt in range(MAX_RETRIES + 1):
        # 1. Build your existing prompt
        prompt = DEV_PROMPT_TEMPLATE.format(
            task_description=req.user_prompt,
            context_blocks=context_blocks,
        )

        # 2. If this is a retry, append a short error feedback block
        if attempt > 0 and last_error is not None:
            feedback = textwrap.dedent(f"""
            --- RETRY ATTEMPT {attempt} ---
            Your previous response failed to parse as valid JSON or did not match the expected schema.

            Python error:
            {last_error.__class__.__name__}: {last_error}

            You MUST regenerate the ENTIRE JSON object.
            Do NOT include any explanation or text outside the JSON.
            """)
            prompt += "\n\n" + feedback

        try:
            # 3. Call your existing DeepSeek client
            raw_output = await call_deepseek(prompt)

            # 4. Your existing parse + validation path:
            parsed = json.loads(raw_output)
            analysis = DevTaskAnalysis(**parsed)
            analysis = validate_suggested_changes(analysis, req.context_files)

            logger.info(f"[DevCouncil] Dev analysis succeeded on attempt {attempt + 1}.")
            break  # ✅ Success – exit the loop

        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            logger.warning(
                f"[DevCouncil] Attempt {attempt + 1} failed (JSON/Validation): "
                f"{e.__class__.__name__}: {e}"
            )

            if attempt == MAX_RETRIES:
                # 5. Final Failure: Build a safe, structured fallback
                logger.error("[DevCouncil] All retries failed; building fallback analysis.")

                # This uses ONLY the existing DevTaskAnalysis fields.
                analysis = DevTaskAnalysis(
                    summary="Dev Council failed to produce valid JSON after retries.",
                    reasoning=(
                        f"Final parse/validation error ({e.__class__.__name__}): {e}. "
                        f"Raw output (truncated and also stored in raw_output): {raw_output[:400]}"
                    ),
                    suggested_changes=[],
                    example_code=None,
                    tests_suggested=[],
                    risks={
                        # Pack failure metadata into the existing risks structure
                        "complexity": 0,
                        "behavior_risks": [
                            "No automated changes were applied for this task due to JSON failure."
                        ],
                        "notes": f"Last JSON error: {e.__class__.__name__}"
                    },
                )
                break  # Exit after fallback

    # 6. Return final result – analysis is guaranteed to be set
    return DevTaskResponse(
        task_id=req.task_id,
        task_type=req.task_type,
        model=DEV_COUNCIL_MODEL,
        raw_output=raw_output,  # last output, even if bad JSON
        analysis=analysis,
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "council": DEV_COUNCIL_NAME,
        "model": DEV_COUNCIL_MODEL,
    }


@app.post("/dev/analyze", response_model=DevTaskResponse)
async def analyze_dev(req: DevTaskRequest):
    """
    Main Dev Council endpoint.
    """
    return await run_dev_analysis(req)


@app.post("/dev_council/analyse", response_model=DevTaskResponse)
async def analyze_dev_legacy(req: DevTaskRequest):
    """
    Backwards-compatible endpoint for existing node_agent code.

    The node agent currently calls DEV_COUNCIL_URL + '/dev_council/analyse'.
    This alias ensures those requests hit the same logic as /dev/analyze.
    """
    return await run_dev_analysis(req)
