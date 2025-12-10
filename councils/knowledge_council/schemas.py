# ~/bobiverse/councils/knowledge_council/schemas.py

from typing import Optional, List
from pydantic import BaseModel


class KnowledgeTaskRequest(BaseModel):
    """
    Incoming request to Knowledge Bob.
    """
    task_id: str
    task_type: str
    question: str
    extra_context: Optional[str] = None


class KnowledgeTaskAnalysis(BaseModel):
    """
    Structured analysis returned by Knowledge Bob.
    """
    answer: str
    reasoning: str
    followups: List[str]


class KnowledgeTaskResponse(BaseModel):
    """
    Full response including raw LLM output and parsed analysis.
    """
    task_id: str
    task_type: str
    model: str
    raw_output: str
    analysis: KnowledgeTaskAnalysis
