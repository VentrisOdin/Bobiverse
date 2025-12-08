#!/usr/bin/env python
import os
import sys
import uuid
import textwrap
import json
import requests

# Toggle this to True once you have an LLM endpoint wired up
USE_LLM = False

REFLECTOR_HOST = os.environ.get("BOBIVERSE_REFLECTOR_HOST", "http://localhost:5081")


def fetch_insights():
    url = f"{REFLECTOR_HOST}/reflector/insights"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def fetch_latest_lesson_id():
    """
    Use the most recent lesson as the 'motivation' for any proposal.
    If there are no lessons yet, return None.
    """
    url = f"{REFLECTOR_HOST}/reflector/lessons/recent"
    resp = requests.get(url, params={"limit": 1}, timeout=5)
    resp.raise_for_status()
    lessons = resp.json()
    if not lessons:
        return None
    return lessons[0]["id"]


# ---------------- Heuristic Brain (current behaviour) ---------------- #

def heuristic_proposal_from_insights(insights: dict) -> dict | None:
    """
    Simple non-LLM Reflector Brain.

    For now:
    - If there are Dev Council 422 errors, propose a PROMPT_TWEAK to tighten JSON output.
    - Otherwise, return None (no proposal).
    """
    top_errors = insights.get("top_error_types", [])
    summary = insights.get("summary", {}) or {}
    total_failures = summary.get("failed_count", 0)

    dev_422_count = 0
    for e in top_errors:
        etype = e.get("error_type", "") or ""
        if "Dev Council error: 422" in etype:
            dev_422_count += e.get("count", 0)

    if dev_422_count == 0 or total_failures == 0:
        print("[ReflectorBrain] (heuristic) No dev_council 422 errors detected; skipping proposal.")
        return None

    description = (
        "Dev Council has repeated 422 validation errors on /dev_council/analyse. "
        "Propose tightening the system prompt to enforce strict JSON schema output."
    )

    # Placeholder payload – later replaced by a real LLM-generated prompt
    action_payload = {
        "key": "SYSTEM_PROMPT",
        "new_value": textwrap.dedent(
            """
            You are the Dev Council model in the Bobiverse.

            You MUST respond with a single JSON object ONLY, and nothing else.
            Do not include explanations, markdown, or natural language outside the JSON.

            The JSON MUST strictly follow the schema given in the prompt.
            If you are unsure, still output a best-effort JSON object that matches the schema.
            """
        ).strip(),
    }

    proposal = {
        "proposal_uuid": str(uuid.uuid4()),
        "proposal_type": "PROMPT_TWEAK",
        "target_module": "dev_council",
        "motivation_lesson_id": fetch_latest_lesson_id(),
        "risk_score": 3,
        "description": description,
        "action_payload": action_payload,
        "source": "heuristic-reflector-brain",
    }
    return proposal


# ---------------- LLM Brain (future behaviour) ---------------- #

def build_llm_prompt(insights: dict) -> str:
    """
    Build the text prompt to send to your LLM.

    You will later wire this to DeepSeek / Dev Council / etc.
    """
    insights_json = json.dumps(insights, indent=2)

    # This is the instruction the LLM will see.
    # It must respond with a SINGLE JSON OBJECT ONLY, no extra text.
    prompt = textwrap.dedent(
        f"""
        You are the Reflector Brain ("Architect Bob") of the Bobiverse.
        Your job is to read system-wide telemetry and propose SMALL, SAFE improvements.

        You are given the latest Reflector insights as JSON:

        {insights_json}

        Based on this data, generate EXACTLY ONE JSON OBJECT as your output.
        DO NOT include any explanation, markdown, or text outside the JSON.

        The JSON MUST strictly follow this schema:

        {{
          "proposal_uuid": "string-uuid",
          "proposal_type": "PROMPT_TWEAK | ROUTING_POLICY | MODULE_ISOLATION | EXPERIMENT",
          "target_module": "name of the module this proposal affects (e.g. 'dev_council')",
          "motivation_lesson_id": null or integer lesson id (use null if unknown),
          "risk_score": 1-5 integer (1 = low risk, 5 = system-critical change),
          "description": "Short human-readable summary of the proposed change",
          "action_payload": {{
             "key": "What configuration or prompt key to change (e.g. 'SYSTEM_PROMPT')",
             "new_value": "The full new value for that key"
          }},
          "source": "short string describing the brain, e.g. 'llm-deepseek'"
        }}

        Rules:
        - If everything looks stable, you may still propose a low-risk EXPERIMENT.
        - If a single module has a clearly worse failure rate (e.g. dev_council 422 errors),
          focus on that module first and use proposal_type = "PROMPT_TWEAK".
        - Always keep risk_score at 3 or below for prompt tweaks. Reserve 4-5 for very large changes.
        - Only output the JSON object, nothing else.
        """
    ).strip()

    return prompt


def call_llm(prompt: str) -> str:
    """
    Placeholder for LLM call.

    You will adapt this to your actual LLM endpoint (DeepSeek via Ollama, OpenAI, etc).

    For now, it just raises NotImplementedError so you don't forget to implement it
    before switching USE_LLM=True.
    """
    raise NotImplementedError("call_llm() is not wired to an LLM endpoint yet.")


def generate_proposal_via_llm(insights: dict) -> dict | None:
    """
    LLM-powered Reflector Brain.

    - Builds a prompt with the insights.
    - Sends to LLM.
    - Parses the returned JSON into a proposal dict.
    """
    prompt = build_llm_prompt(insights)
    raw = call_llm(prompt)

    # Expect RAW to be a pure JSON object as text
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[ReflectorBrain] LLM output was not valid JSON: {e}", file=sys.stderr)
        return None

    # Basic validation & normalisation
    # Ensure required keys exist; fill defaults if missing.
    proposal = {
        "proposal_uuid": obj.get("proposal_uuid") or str(uuid.uuid4()),
        "proposal_type": obj.get("proposal_type") or "PROMPT_TWEAK",
        "target_module": obj.get("target_module") or "dev_council",
        "motivation_lesson_id": obj.get("motivation_lesson_id") or fetch_latest_lesson_id(),
        "risk_score": int(obj.get("risk_score") or 3),
        "description": obj.get("description") or "LLM-generated proposal.",
        "action_payload": obj.get("action_payload") or {
            "key": "SYSTEM_PROMPT",
            "new_value": "<LLM_DID_NOT_SUPPLY_NEW_VALUE>",
        },
        "source": obj.get("source") or "llm-reflector-brain",
    }

    # Clamp risk_score between 1 and 5
    if proposal["risk_score"] < 1:
        proposal["risk_score"] = 1
    if proposal["risk_score"] > 5:
        proposal["risk_score"] = 5

    return proposal


# ---------------- Orchestration ---------------- #

def generate_proposal_from_insights(insights: dict) -> dict | None:
    """
    Main decision point for the Brain:
    - Try LLM if enabled.
    - Fall back to heuristic if LLM is disabled or fails.
    """
    if USE_LLM:
        print("[ReflectorBrain] LLM mode enabled; attempting LLM proposal...")
        try:
            proposal = generate_proposal_via_llm(insights)
            if proposal:
                return proposal
            else:
                print("[ReflectorBrain] LLM returned no proposal; falling back to heuristic.")
        except NotImplementedError:
            print("[ReflectorBrain] call_llm() not implemented yet; falling back to heuristic.")
        except Exception as e:
            print(f"[ReflectorBrain] LLM call failed: {e}; falling back to heuristic.", file=sys.stderr)

    # Either LLM is disabled or failed → heuristic fallback
    return heuristic_proposal_from_insights(insights)


def submit_proposal(proposal: dict):
    url = f"{REFLECTOR_HOST}/reflector/proposals"
    resp = requests.post(url, json=proposal, timeout=10)
    resp.raise_for_status()
    return resp.json()


def main():
    try:
        insights = fetch_insights()
    except Exception as e:
        print(f"[ReflectorBrain] Failed to fetch insights: {e}", file=sys.stderr)
        sys.exit(1)

    proposal = generate_proposal_from_insights(insights)
    if not proposal:
        # Nothing to do
        sys.exit(0)

    print("[ReflectorBrain] Generated proposal:")
    print(f"  type         : {proposal['proposal_type']}")
    print(f"  target_module: {proposal['target_module']}")
    print(f"  description  : {proposal['description']}")

    try:
        created = submit_proposal(proposal)
    except Exception as e:
        print(f"[ReflectorBrain] Failed to submit proposal: {e}", file=sys.stderr)
        sys.exit(1)

    print("[ReflectorBrain] Proposal stored with id:", created["id"])


if __name__ == "__main__":
    main()
