from __future__ import annotations
import os
from typing import List

from fastapi import FastAPI, HTTPException
from urllib.parse import urlparse

from .schemas import TeacherResearchRequest, TeacherResearchResponse, TeacherSource, TeacherChunk
from .trust import DEFAULT_ALLOWLIST, is_allowed, domain_of, trust_for_domain


from .fetchers.wikipedia import fetch_wikipedia_summary
from .fetchers.arxiv import fetch_arxiv_top
from .fetchers.pubmed import fetch_pubmed_top
from .fetchers.nhs import fetch_nhs_top


APP_TITLE = "Teacher Council v1"
DEFAULT_PORT = int(os.getenv("TEACHER_COUNCIL_PORT", "8013"))

app = FastAPI(title=APP_TITLE)


def _make_chunks(question: str, sources: List[TeacherSource]) -> List[TeacherChunk]:
    chunks: List[TeacherChunk] = []
    for s in sources:
        if not s.snippet:
            continue
        chunks.append(
            TeacherChunk(
                text=s.snippet,
                metadata={
                    "source": "teacher_council",
                    "origin": s.domain,
                    "url": s.url,
                    "title": s.title,
                    "trust": s.trust,
                    "question": question,
                },
            )
        )
    return chunks


def _summarise(question: str, sources: List[TeacherSource]) -> str:
    # v1 = deterministic “compressed digest” (no LLM needed yet)
    if not sources:
        return "No trusted sources were found for this question on the current allowlist."
    lines = [f"Question: {question}", "", "Findings (from trusted sources):"]
    for i, s in enumerate(sources, start=1):
        snip = (s.snippet or "").strip()
        if snip:
            lines.append(f"{i}. {s.title} — {snip[:400]}")
        else:
            lines.append(f"{i}. {s.title} — (citation only)")
    lines.append("")
    lines.append("Citations:")
    for s in sources:
        lines.append(f"- {s.url}")
    return "\n".join(lines)


@app.get("/health")
def health():
    return {"status": "ok", "service": "teacher_council", "version": "v1"}


@app.post("/teacher_council/research", response_model=TeacherResearchResponse)
def research(req: TeacherResearchRequest):
    allowlist = set(req.domains_allow) if req.domains_allow else set(DEFAULT_ALLOWLIST)


    candidates = []

    # Definition-first sources
    nhs = fetch_nhs_top(req.question)
    if nhs:
        candidates.append(nhs)

    w = fetch_wikipedia_summary(req.question)
    if w:
        candidates.append(w)

    # Then scholarly sources
    p = fetch_pubmed_top(req.question)
    if p:
        candidates.append(p)

    a = fetch_arxiv_top(req.question)
    if a:
        candidates.append(a)

    # Filter by allowlist + create sources
    sources: List[TeacherSource] = []
    for c in candidates:
        url = c["url"]
        if not is_allowed(url, allowlist):
            continue
        dom = domain_of(url)
        sources.append(
            TeacherSource(
                title=c["title"],
                url=url,
                domain=dom,
                trust=trust_for_domain(dom),
                snippet=c.get("snippet") if req.include_snippets else None,
            )
        )

    sources = sources[: req.max_sources]
    summary = _summarise(req.question, sources)
    chunks = _make_chunks(req.question, sources)

    confidence = 0.25
    if sources:
        # naive confidence heuristic for v1
        confidence = 0.55 if any(s.trust == "high" for s in sources) else 0.45

    return TeacherResearchResponse(
        question=req.question,
        summary=summary,
        confidence=confidence,
        sources=sources,
        chunks=chunks,
    )
