
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
from .fetchers.pubmed import fetch_pubmed_candidates
from .fetchers.web_search import fetch_web_candidates

from .fetchers.nhs import fetch_nhs_candidates
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
    "meaning", "define", "definition", "what", "is", "the", "a", "an", "of", "in", "for", "to", "and",
    "how", "does", "do", "work", "works", "why", "when", "where", "who", "explain"
}
_STOPWORDS |= {"affect", "effects", "effect", "impact", "impacts", "change", "changes"}
def _wiki_query(question: str) -> str:
    q = (question or "").strip()
    m = re.search(r"affect\s+(.*)$", q, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return q

def _question_domain(question: str) -> str:
    q = (question or "").lower()

    # very conservative: only label medical when it's clearly medical
    medical_triggers = [
        "nhs", "symptom", "symptoms", "treatment", "diagnosis", "infection",
        "disease", "illness", "medicine", "antibiotic", "virus", "bacteria",
        "dose", "side effect", "clinic", "gp", "hospital", "condition"
    ]
    if any(t in q for t in medical_triggers):
        return "medical"

    return "general"

def _extract_acronyms(question: str) -> List[str]:
    """
    Returns likely acronyms, e.g. MRSA, HIV, COPD
    """
    return re.findall(r"\b[A-Z]{3,}\b", question or "")

def _stands_for_bonus(snippet: Optional[str]) -> int:
    if not snippet:
        return 0
    s = snippet.lower()
    if "stands for" in s:
        return 3
    if "is short for" in s or "abbreviation" in s:
        return 2
    return 0

def _looks_like_definition(c: Dict[str, Any], question: str) -> bool:
    q = (question or "").lower()
    blob = _candidate_text(c)
    kws = _extract_keywords(question)

    # Strong signals for definition/explanation style
    if any(x in blob for x in [" is a ", " refers to ", " means ", " stands for ", " abbreviation"]):
        return True

    # If acronym is in question, require either "(ACRONYM)" or "stands for"
    # e.g. MRSA → title/snippet contains MRSA or the expanded phrase
    if kws:
        return any(kw in blob for kw in kws)
    return False

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
    url = str(c.get("url", "") or "")
    if "nhs.uk/search/click" in url:
        # remove searchText=... so it can't falsely satisfy keyword matching
        url = url.split("searchText=", 1)[0]
    return _norm(" ".join([
        str(c.get("title", "")),
        str(c.get("snippet", "")),
        url,
    ]))

def _is_relevant(question: str, c: Dict[str, Any]) -> bool:
    kws = _extract_keywords(question)
    if not kws:
        return True

    blob = _candidate_text(c)

    url = (c.get("url") or "").lower()
    if "pubmed.ncbi.nlm.nih.gov" in url:
        # only accept if keyword(s) appear in TITLE or URL (not just abstract noise)
        title = _norm(c.get("title", ""))
        return any(kw in title for kw in kws) or any(kw in url for kw in kws)

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
    def _answer(question: str, sources: List[TeacherSource]) -> str:
        if not sources:
            return "No trusted sources were found for this question on the current allowlist."

        # pick best snippet (prefer high-trust)
        best = next((s for s in sources if s.trust == "high" and (s.snippet or "").strip()), None)
        if not best:
            best = next((s for s in sources if (s.snippet or "").strip()), sources[0])

        snip = re.sub(r"\s+", " ", (best.snippet or "").strip())

        # keep 1–2 sentences
        parts = re.split(r"(?<=[.!?])\s+", snip)
        short = " ".join(parts[:2]).strip()

        if len(short) > 320:
            short = short[:320].rsplit(" ", 1)[0] + "…"

        return f"{short} (Source: {best.domain})"
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


    # Determine question domain for source gating
    q_domain = _question_domain(req.question)



    # Always allowed for all questions: Wikipedia
    wq = _wiki_query(req.question)
    w = fetch_wikipedia_summary(wq)

    logger.info("WIKI_QUERY=%s", wq)
    logger.info("WIKI_RAW=%s", w)

    if w:
        # Wikipedia is a safe baseline; relevance is handled later by ranking anyway
        candidates.append(w)

    # General web discovery (allowlist-filtered)
    if q_domain != "medical":
        for c in fetch_web_candidates(
            req.question,
            allowlist=list(allowlist),
            limit=6,
            search_k=25,
        ):
            candidates.append(c)

    # Only run medical fetchers for medical questions
    if q_domain == "medical":
        for nhs in fetch_nhs_candidates(req.question, limit=3):
            if _is_relevant(req.question, nhs):
                candidates.append(nhs)

        cdc = fetch_cdc_top(req.question)
        if cdc and _is_relevant(req.question, cdc):
            candidates.append(cdc)

        nice = fetch_nice_top(req.question)
        if nice and _is_relevant(req.question, nice):
            candidates.append(nice)

        ukhsa = fetch_ukhsa_top(req.question)
        if ukhsa and _is_relevant(req.question, ukhsa):
            candidates.append(ukhsa)

        for p in fetch_pubmed_candidates(req.question, limit=3):
            if _is_relevant(req.question, p):
                candidates.append(p)

    # a = fetch_arxiv_top(req.question)  # disable for now; too noisy for general Qs


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
        dom = domain_of(url)
        if dom != "wikipedia.org" and not is_allowed(url, allowlist):
            continue
        if not _is_relevant(req.question, c):
            continue

        seen_urls.add(url)
        filtered.append(c)

    filtered.sort(key=lambda c: _rank_key(req.question, c), reverse=True)
    filtered = filtered[: req.max_sources]

    from urllib.parse import unquote, urlparse, parse_qs
    sources: List[TeacherSource] = []
    for c in filtered:
        url = c["url"]
        # Canonicalize NHS click URLs
        if "nhs.uk/search/click" in url:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            nhs_path = qs.get("url", [None])[0]
            if nhs_path and nhs_path.startswith("/conditions/"):
                url = f"https://www.nhs.uk{unquote(nhs_path)}"
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
        primary_domains = {"nhs.uk", "cdc.gov", "who.int", "nih.gov", "nice.org.uk", "ukhsa.gov.uk"}
        supporting_domains = {"ncbi.nlm.nih.gov"}  # PubMed

        primary = [
            s for s in sources
            if s.trust == "high" and s.domain in primary_domains
        ]

        # allow PubMed only as *supporting evidence* if it looks definitional
        supporting = []
        for c in filtered:
            dom = domain_of(c.get("url", ""))
            if dom in supporting_domains and _looks_like_definition(c, req.question):
                supporting.append(
                    TeacherSource(
                        title=c.get("title", "").strip() or dom,
                        url=c["url"],
                        domain=dom,
                        trust=trust_for_domain(dom),
                        snippet=c.get("snippet") if req.include_snippets else None,
                    )
                )

        wiki = [s for s in sources if s.domain == "wikipedia.org"]

        if primary:
            sources = primary[: req.max_sources]
            if len(sources) < req.max_sources and supporting:
                sources.append(supporting[0])
        elif supporting:
            sources = [supporting[0]]
            if wiki and len(sources) < req.max_sources:
                sources.append(wiki[0])
        elif wiki:
            sources = [wiki[0]]



    # Tiny filter: for definition queries, drop PubMed if snippet is not meaningful
    is_definition_query = any(k in req.question.lower() for k in ["what is", "meaning", "define", "definition"])
    if is_definition_query:
        def _good_snip(s: TeacherSource) -> bool:
            sn = (s.snippet or "").strip()
            return len(sn) >= 80  # tune as needed

        sources = [s for s in sources if not (s.domain == "ncbi.nlm.nih.gov" and not _good_snip(s))]

    # Build answer/summary depending on mode

    answer: Optional[str] = None
    summary: str = ""

    if req.mode in ("answer", "both"):
        if sources:
            acronyms = _extract_acronyms(req.question)

            def score_source(s: TeacherSource) -> tuple:
                """
                Higher tuple wins.
                Order:
                1) Has 'stands for' if acronym query
                2) Trust (+1 for Wikipedia if acronym query)
                3) Has snippet
                """
                trust_score = 2 if s.trust == "high" else 1
                if acronyms and s.domain == "wikipedia.org":
                    trust_score += 1
                stands_bonus = _stands_for_bonus(s.snippet) if acronyms else 0
                has_snip = 1 if (s.snippet or "").strip() else 0
                return (stands_bonus, trust_score, has_snip)

            ranked = sorted(sources, key=score_source, reverse=True)
            best = ranked[0] if ranked else None

            if best and best.snippet:
                snip = re.sub(r"\s+", " ", best.snippet.strip())
                parts = re.split(r"(?<=[.!?])\s+", snip)
                answer = " ".join(parts[:2]).strip()

    if req.mode in ("research", "both"):
        summary = _summarise(req.question, sources)
    else:
        # Optional: keep summary minimal in answer-only mode
        summary = "Answer-only mode. See sources for citations."

    chunks = _make_chunks(req.question, sources)


    # Set confidence based on number of sources
    confidence = 0.2 if not sources else 0.7 if len(sources) == 1 else 0.9

    return TeacherResearchResponse(
        question=req.question,
        answer=answer,
        summary=summary,
        confidence=confidence,
        sources=sources,
        chunks=chunks,
        mode=req.mode,  # echo mode for debugging
    )
