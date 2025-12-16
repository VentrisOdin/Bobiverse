from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field


class TeacherResearchRequest(BaseModel):
    question: str = Field(..., min_length=3)
    max_sources: int = Field(6, ge=1, le=12)
    domains_allow: Optional[List[str]] = None  # optional override allowlist
    include_snippets: bool = True

    # NEW: output mode
    mode: Literal["answer", "research", "both"] = "both"


class TeacherSource(BaseModel):
    title: str
    url: str
    domain: str
    trust: str  # "high" | "medium" | "low"
    snippet: Optional[str] = None


class TeacherChunk(BaseModel):
    text: str
    metadata: Dict[str, Any]


class TeacherResearchResponse(BaseModel):
    question: str
    mode: Literal["answer", "research", "both"] = "both"
    answer: Optional[str] = None
    summary: str
    confidence: float
    sources: List[TeacherSource]
    chunks: List[TeacherChunk]
