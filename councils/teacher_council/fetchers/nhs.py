
from __future__ import annotations

import re
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

NHS_SEARCH = "https://www.nhs.uk/search/"
UA = {"User-Agent": "Bobiverse-TeacherCouncil/1.0"}

_STOP = {"meaning","define","definition","what","is","the","a","an","of","in","for","to","and"}

def _keywords(query: str) -> List[str]:
    toks = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", query or "")]
    toks = [t for t in toks if t not in _STOP and len(t) > 1]
    # prefer longer tokens first
    toks.sort(key=lambda x: (-len(x), x))
    return toks

def _looks_relevant(query: str, title: str, url: str, snippet: str | None = None) -> bool:
    kws = _keywords(query)
    if not kws:
        return True
    blob = (title or "").lower() + " " + (url or "").lower()
    # For NHS, title + url match is the safest filter (snippets can be generic)
    return any(kw in blob for kw in kws)

def _extract_result_links(soup: BeautifulSoup) -> List[str]:
    links: List[str] = []
    # NHS search cards/panels
    for a in soup.select("a.nhsuk-list-panel__link, a.nhsuk-card__link"):
        href = a.get("href")
        if href:
            links.append(href)

    # fallback: any link in main content area that looks internal
    if not links:
        for a in soup.select("main a[href^='/']"):
            href = a.get("href")
            if href:
                links.append(href)

    # de-dupe while preserving order
    seen = set()
    out = []
    for h in links:
        u = urljoin("https://www.nhs.uk", h)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def _fetch_page_snippet(url: str, timeout: int) -> Dict[str, Optional[str]]:
    r = requests.get(url, timeout=timeout, headers=UA)
    if r.status_code != 200:
        return {"title": None, "snippet": None}

    soup = BeautifulSoup(r.text, "html.parser")

    h1 = soup.select_one("h1")
    title = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else None)

    # Prefer first meaningful paragraph
    p = soup.select_one("main p")
    snippet = p.get_text(" ", strip=True) if p else None
    if snippet:
        snippet = snippet[:800]

    return {"title": title, "snippet": snippet}

def fetch_nhs_candidates(query: str, limit: int = 5, timeout: int = 15) -> List[dict]:
    """
    Returns up to `limit` relevant NHS candidates:
      {"title": str, "url": str, "snippet": str|None}
    Relevance is checked against query-derived keywords (no hardcoded disease terms).
    """
    limit = max(1, min(int(limit), 10))

    r = requests.get(NHS_SEARCH, params={"q": query}, timeout=timeout, headers=UA)
    if r.status_code != 200:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    urls = _extract_result_links(soup)

    candidates: List[dict] = []
    for url in urls[: max(limit * 3, 10)]:  # fetch a bit more, then filter down
        page = _fetch_page_snippet(url, timeout=timeout)
        title = page["title"] or "NHS"
        snippet = page["snippet"]

        if not _looks_relevant(query, title, url, snippet):
            continue

        candidates.append({"title": title, "url": url, "snippet": snippet})
        if len(candidates) >= limit:
            break

    return candidates

def fetch_nhs_top(query: str, timeout: int = 15) -> dict | None:
    """
    Backwards-compatible: returns the top NHS candidate (or None).
    Prefer using fetch_nhs_candidates() in the service.
    """
    cands = fetch_nhs_candidates(query, limit=1, timeout=timeout)
    return cands[0] if cands else None
