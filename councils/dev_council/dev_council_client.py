import os
import json
from typing import Optional

import httpx
from dotenv import load_dotenv

from .schemas import DevTaskRequest, DevTaskResponse

load_dotenv()

DEV_COUNCIL_URL = os.getenv("DEV_COUNCIL_URL", "http://localhost:8011")


async def analyse_dev_task_async(
    task_type: str,
    description: str,
    code_snippet: Optional[str] = None,
    repo_context: Optional[str] = None,
    extra_instructions: Optional[str] = None,
    task_id: Optional[str] = None,
) -> DevTaskResponse:
    # Normalise task_id to string for Pydantic / FastAPI
    if task_id is not None and not isinstance(task_id, str):
        task_id = str(task_id)

    req = DevTaskRequest(
        task_type=task_type,
        description=description,
        code_snippet=code_snippet,
        repo_context=repo_context,
        extra_instructions=extra_instructions,
        task_id=task_id,
    )

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{DEV_COUNCIL_URL}/dev_council/analyse",
            json=req.model_dump(),
        )
        resp.raise_for_status()
        data = resp.json()
        return DevTaskResponse(**data)


def analyse_dev_task(
    task_type: str,
    description: str,
    code_snippet: Optional[str] = None,
    repo_context: Optional[str] = None,
    extra_instructions: Optional[str] = None,
    task_id: Optional[str] = None,
) -> DevTaskResponse:
    """
    Synchronous helper wrapper (for quick scripts / REPL use).
    """
    import asyncio

    return asyncio.run(
        analyse_dev_task_async(
            task_type=task_type,
            description=description,
            code_snippet=code_snippet,
            repo_context=repo_context,
            extra_instructions=extra_instructions,
            task_id=task_id,
        )
    )


if __name__ == "__main__":
    # quick manual test
    resp = analyse_dev_task(
        task_type="code_review",
        description="Review this function for potential bugs and improvements.",
        code_snippet="""
def calculate_max_drawdown(prices):
    max_dd = 0
    peak = prices[0]
    for price in prices:
        if price > peak:
            peak = price
        drawdown = (peak - price) / peak
        if drawdown > max_dd:
            max_dd = drawdown
    return max_dd
""".strip(),
    )

    print("=== SUMMARY ===")
    print(resp.analysis.summary)
    print("\n=== SUGGESTED CHANGES ===")
    print(resp.analysis.suggested_changes)
    print("\n=== EXAMPLE CODE ===")
    print(resp.analysis.example_code or "None")
