# councils/dev_council/schemas.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class CodeSnippet(BaseModel):
    file: str                  # e.g. "orchestrator/main.py"
    description: str           # human description of what this snippet is
    before_code: str           # must exist EXACTLY in the file
    after_code: str            # proposed replacement


class SuggestedChange(BaseModel):
    id: str
    title: str
    description: str
    complexity: int            # 1–5
    snippets: List[CodeSnippet]


class DevTaskAnalysis(BaseModel):
    summary: str
    reasoning: str
    suggested_changes: List[SuggestedChange]
    example_code: Optional[str] = None
    tests_suggested: Optional[List[str]] = None
    risks: Optional[Dict[str, Any]] = None


class DevTaskRequest(BaseModel):
    task_id: str
    task_type: str              # e.g. "dev"
    user_prompt: str            # what bobctl / orchestrator asked for
    context_files: Dict[str, str]  # {"orchestrator/main.py": "<file contents>", ...}
    details: Optional[Any] = None  # can be JSON string or dict


class DevTaskResponse(BaseModel):
    task_id: str
    task_type: str
    model: str
    raw_output: str
    analysis: DevTaskAnalysis
