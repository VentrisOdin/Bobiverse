from __future__ import annotations

import os
import re
from typing import List, Dict, Any, Optional, Set, Tuple

from fastapi import FastAPI
from urllib.parse import urlparse

from .schemas import TeacherResearchRequest, TeacherResearchResponse, TeacherSource, TeacherChunk
from .trust import DEFAULT_ALLOWLIST, is_allowed, domain_of, trust_for_domain

from .fetchers.wikipedia import fetch_wikipedia_summary
from .fetchers.arxiv import fetch_arxiv_top
from .fetchers.pubmed import fetch_pubmed_top


from .fetchers.nhs import fetch_nhs_top
from .fetchers.cdc import fetch_cdc_top
from .fetchers.nice import fetch_nice_top
from .fetchers.ukhsa import fetch_ukhsa_top

import logging
logger = logging.getLogger("uvicorn.error")

APP_TITLE = "Teacher Council v1"
DEFAULT_PORT = int(os.getenv("TEACHER_COUNCIL_PORT", "8013"))

app = FastAPI(title=APP_TITLE)


# ---------------------------
# Relevance + Ranking Helpers
# ---------------------------

_STOPWORDS: Set[str] = {
    "meaning", "define", "definition", "what", "is", "the", "a", "an", "of", "in", "for", "to", "and"
}

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _extract_keywords(question: str) -> List[str]:
    """
    Pulls strong tokens from the question.
    - keeps acronyms like MRSA
    - removes stopwords
    """
    q = (question or "").strip()
    raw = re.findall(r"[A-Za-z0-9]+", q)
    if not raw:
        return []
    kws: List[str] = []
    for t in raw:
        if len(t) <= 1:
            continue
        if t.lower() in _STOPWORDS:
            continue
        # Keep original-case acronyms as lower for matching
        kws.append(t.lower())
    # Prefer longer/rarer-looking tokens first
    kws.sort(key=lambda x: (-len(x), x))
    return kws

def _candidate_text(c: Dict[str, Any]) -> str:
    return _norm(" ".join([
        str(c.get("title", "")),
        str(c.get("snippet", "")),
        str(c.get("url", "")),
    ]))

def _is_relevant(question: str, c: Dict[str, Any]) -> bool:
    """
    Hard relevance filter:
    - If the question contains a strong token (e.g. 'mrsa'),
      require at least one strong token to appear in title/snippet/url.
    """
    kws = _extract_keywords(question)
    if not kws:
        return True

    blob = _candidate_text(c)

    # If user asked with an acronym (MRSA), that token will be in kws.
    # Require at least one keyword match.
    return any(kw in blob for kw in kws)

def _definitiony_bonus(c: Dict[str, Any]) -> int:
    """
    Small bonus for likely definitional pages.
    (We do NOT want NHS search to return random conditions pages unrelated to the keyword.)
    """
    t = _norm(c.get("title", ""))
    u = _norm(c.get("url", ""))
    s = _norm(c.get("snippet", ""))

    bonus = 0
    if any(x in t for x in ["what is", "definition", "overview", "about", "meaning"]):
        bonus += 1
    if any(x in s for x in ["is a", "refers to", "means", "defined as"]):
        bonus += 1
    # Wikipedia summaries tend to be definitional
    if "wikipedia.org" in u:
        bonus += 1
    return bonus

def _rank_key(question: str, c: Dict[str, Any]) -> Tuple[int, int, int]:
    """
    Higher is better.
    1) Trust (high > medium > low)
    2) Relevance (relevant > not relevant)  [but we already filter, still kept for safety]
    3) Definition-likeness bonus
    """
    url = c.get("url", "")
    dom = domain_of(url) if url else ""
    trust = trust_for_domain(dom)
    trust_score = 3 if trust == "high" else 2 if trust == "medium" else 1

    rel_score = 1 if _is_relevant(question, c) else 0
    def_bonus = _definitiony_bonus(c)

    return (trust_score, rel_score, def_bonus)


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

    candidates: List[Dict[str, Any]] = []

    # Definition-first sources (but ONLY if relevant)



    nhs = fetch_nhs_top(req.question)
    logger.info("NHS fetch: %s", "OK" if nhs else "NONE")
    if nhs:
        candidates.append(nhs)

    cdc = fetch_cdc_top(req.question)
    logger.info("CDC fetch: %s", "OK" if cdc else "NONE")
    if cdc and _is_relevant(req.question, cdc):
        candidates.append(cdc)

    nice = fetch_nice_top(req.question)
    logger.info("NICE fetch: %s", "OK" if nice else "NONE")
    if nice and _is_relevant(req.question, nice):
        candidates.append(nice)

    ukhsa = fetch_ukhsa_top(req.question)
    logger.info("UKHSA fetch: %s", "OK" if ukhsa else "NONE")
    if ukhsa and _is_relevant(req.question, ukhsa):
        candidates.append(ukhsa)

    w = fetch_wikipedia_summary(req.question)
    logger.info("Wikipedia fetch: %s", "OK" if w else "NONE")
    if w:
        candidates.append(w)

    # Then scholarly sources (also gated)

    p = fetch_pubmed_top(req.question)
    logger.info("PubMed fetch: %s", "OK" if p else "NONE")
    if p:
        candidates.append(p)

    a = fetch_arxiv_top(req.question)
    logger.info("arXiv fetch: %s", "OK" if a else "NONE")
    if a:
        candidates.append(a)


    # --- Logging for debugging allowlist and candidate filtering ---
    logger.info("ALLOWLIST = %s", sorted(list(allowlist)))
    logger.info(
        "RAW CANDIDATES = %s",
        [{
            "title": c.get("title"),
            "url": c.get("url"),
            "relevant": _is_relevant(req.question, c),
        } for c in candidates]
    )

    for c in candidates:
        url = c["url"]
        dom = domain_of(url)
        allowed = is_allowed(url, allowlist)
        relevant = _is_relevant(req.question, c)
        logger.info("FILTER url=%s dom=%s allowed=%s relevant=%s", url, dom, allowed, relevant)

    # Filter by allowlist + de-dupe + relevance + rank
    seen_urls: Set[str] = set()
    filtered: List[Dict[str, Any]] = []
    for c in candidates:
        url = c.get("url", "")
        if not url or url in seen_urls:
            continue
        if not is_allowed(url, allowlist):
            continue
        if not _is_relevant(req.question, c):
            continue

        seen_urls.add(url)
        filtered.append(c)

    filtered.sort(key=lambda c: _rank_key(req.question, c), reverse=True)
    filtered = filtered[: req.max_sources]

    sources: List[TeacherSource] = []
    for c in filtered:
        url = c["url"]
        dom = domain_of(url)
        sources.append(
            TeacherSource(
                title=c.get("title", "").strip() or dom,
                url=url,
                domain=dom,
                trust=trust_for_domain(dom),
                snippet=c.get("snippet") if req.include_snippets else None,
            )
        )


    # Definition guardrail
    is_definition_query = any(
        k in req.question.lower()
        for k in ["what is", "meaning", "define", "definition"]
    )

    if is_definition_query:
        definition_preferred_domains = {
            "nhs.uk",
            "who.int",
            "cdc.gov",
            "gov.uk",
            "wikipedia.org",
        }

        # Keep definition-style sources first
        definition_sources = [
            s for s in sources
            if s.domain in definition_preferred_domains
        ]

        if definition_sources:
            sources = definition_sources

    summary = _summarise(req.question, sources)
    chunks = _make_chunks(req.question, sources)

    confidence = 0.25
    if sources:
        confidence = 0.55 if any(s.trust == "high" for s in sources) else 0.45

    return TeacherResearchResponse(
        question=req.question,
        summary=summary,
        confidence=confidence,
        sources=sources,
        chunks=chunks,
    )
