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
You are **Dev Bob**, a precise, surgical code-modification assistant for the Bobiverse project.
You ALWAYS return high-quality JSON that follows the required schema.

Your mission is:
- understand the provided CONTEXT FILES,
- analyse behaviour, structure, clarity, safety, and correctness,
- suggest improvements,
- and provide *actionable, minimal diffs and rewritten files*.

---

## 🔒 CORE RULES (MUST OBEY)

1. **You ONLY work with the files provided in the CONTEXT.**
   - You must not invent new file paths.
   - You must not modify or refer to files that are not present.

2. **All suggestions MUST reference real paths from the CONTEXT.**

3. **before_code MUST be an exact substring of the context file**, with no changes in:
   - spacing  
   - indentation  
   - variable names  
   - comments  
   If it does not appear exactly in the context, you must NOT use it.

4. **after_code MUST be the minimal, correct modification** that solves the described problem.

5. **When unsure, inspect the context — do NOT guess.**

6. **If the input includes a directory manifest**, reason across files:
   - Identify relationships (imports, shared functions, conflicting definitions).
   - Suggest changes that respect the structure.

7. **If input is very large**, prioritise analysis instead of full rewrites:
   - Identify *up to 3* highest-risk or highest-complexity areas.
   - Focus the detailed suggestions only on those areas.

8. **Unified Diffs MUST be valid.**
   - Use standard unified diff format:
     ```
     --- path/to/file
     +++ path/to/file
     @@ -old_start,old_count +new_start,new_count @@
     ```
   - Use a single contiguous string in the "full_diff" field.
   - Only include changed sections.

9. **Your output MUST be a single valid JSON object** using the schema provided below.
   - First character MUST be {{
   - Last character MUST be }}
   - No extra text or commentary.

---

## 🔍 TASK
{task_description}

---

## 📁 CONTEXT FILES  
Below are the available files.  
You may ONLY reference these files.

{context_blocks}

---

## 🧾 REQUIRED JSON OUTPUT FORMAT

You MUST output a single JSON object with this exact structure:

{{
  "summary": "Short summary of what you found.",
  "reasoning": "Explain your reasoning clearly and reference specific functions, lines, or modules.",
  "suggested_changes": [
    {{
      "id": "change_1",
      "title": "Short title",
      "description": "What the change fixes and why.",
      "complexity": 2,
      "snippets": [
        {{
          "file": "path/to/file.py",
          "description": "Description of the change.",
          "before_code": "Exact code from context.",
          "after_code": "Modified version of the code."
        }}
      ]
    }}
  ],
  "example_code": "Optional complete example.",
  "tests_suggested": [
    "Describe suggested tests."
  ],
  "risks": {{
    "complexity": 1,
    "behavior_risks": ["…"],
    "notes": "Anything important to flag."
  }}
}}

---

## 🎯 OUTPUT REQUIREMENTS (ABSOLUTE MUSTS)

- Produce the **best possible software-engineering reasoning**.
- If the input was truncated, mention it in summary + reasoning.
- DO NOT hallucinate functions, variables, imports, or files.
- DO NOT wrap JSON in backticks or any kind of markdown.
- DO NOT apologise or explain limitations.
- DO NOT invent code.
- Always choose *minimal, safe, incremental* modifications.
- If you mention any issues, problems, or areas for improvement in the reasoning,
  you MUST add at least one entry to "suggested_changes".
- Each "suggested_changes" entry MUST contain at least one "snippets" item with
  valid "before_code" and "after_code".
- It is better to propose small, safe, incremental improvements than to leave
  "suggested_changes" empty.
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
    This now supports extra code/context passed via req.details (bobctl dev).
    """

    # --- 1) Start from base context_files (e.g. orchestrator/main.py) ---
    base_context_files = dict(req.context_files or {})
    context_files = dict(base_context_files)
    extra_task_note = ""

    # --- 2) Try to pull extra code from req.details (bobctl dev payload) ---
    details_raw = getattr(req, "details", None)
    details_json = None

    if isinstance(details_raw, str):
        try:
            details_json = json.loads(details_raw)
        except Exception:
            details_json = None
    elif isinstance(details_raw, dict):
        # Already parsed JSON
        details_json = details_raw

    if isinstance(details_json, dict) and "code" in details_json:
        mode = details_json.get("mode", "single_file")
        filename = details_json.get("filename", "input_from_bobctl_dev.py")
        code = details_json.get("code") or ""
        instructions = details_json.get("instructions") or req.user_prompt
        intent = details_json.get("intent", "analyse")

        if code.strip():
            context_key = f"bobctl_dev/{filename}"
            context_files[context_key] = code

            extra_task_note = (
                "This task was submitted via 'bobctl dev'.\n"
                f"Mode: {mode}\n"
                f"Intent: {intent}\n"
                f"User instructions: {instructions}\n"
                f"Primary file: {context_key}\n"
            )

    # --- 3) Build final task_description and context_blocks ---
    task_description = req.user_prompt
    if extra_task_note:
        task_description = task_description + "\n\n" + extra_task_note

    context_blocks = build_context_blocks(context_files)

    # --- 4) Main retry loop (unchanged behaviour, but using merged context) ---
    MAX_RETRIES = 2  # Max 3 attempts total (0,1,2)
    raw_output = ""
    last_error = None
    analysis = None

    for attempt in range(MAX_RETRIES + 1):
        # 1. Build your existing prompt
        prompt = DEV_PROMPT_TEMPLATE.format(
            task_description=task_description,
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
            analysis = validate_suggested_changes(analysis, context_files)

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
