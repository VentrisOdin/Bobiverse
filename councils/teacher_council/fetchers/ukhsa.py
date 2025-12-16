from __future__ import annotations

import re
from typing import List, Optional, Dict
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

UA = {"User-Agent": "Bobiverse-TeacherCouncil/1.0"}
GOVUK_SEARCH = "https://www.gov.uk/search/all"

_STOP = {"meaning","define","definition","what","is","the","a","an","of","in","for","to","and"}

def _keywords(query: str) -> List[str]:
    toks = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", query or "")]
    toks = [t for t in toks if t not in _STOP and len(t) > 1]
    toks.sort(key=lambda x: (-len(x), x))
    return toks

def _looks_relevant(query: str, title: str, url: str) -> bool:
    kws = _keywords(query)
    if not kws:
        return True
    blob = (title or "").lower() + " " + (url or "").lower()
    return any(kw in blob for kw in kws)

def _fetch_govuk_snippet(url: str, timeout: int) -> Dict[str, Optional[str]]:
    r = requests.get(url, timeout=timeout, headers=UA)
    if r.status_code != 200:
        return {"title": None, "snippet": None}

    soup = BeautifulSoup(r.text, "html.parser")

    # GOV.UK pages: title often in h1.govuk-heading-l
    h1 = soup.select_one("h1")
    title = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else None)

    # snippet: try lead paragraph / first body paragraph
    p = (
        soup.select_one(".gem-c-lead-paragraph")
        or soup.select_one(".govuk-govspeak p")
        or soup.select_one("main p")
        or soup.select_one("article p")
    )
    snippet = p.get_text(" ", strip=True) if p else None
    if snippet:
        snippet = snippet[:800]

    return {"title": title, "snippet": snippet}

def fetch_ukhsa_candidates(query: str, limit: int = 5, timeout: int = 12) -> List[dict]:
    """
    Returns up to `limit` relevant UKHSA candidates via GOV.UK search:
      {"title": str, "url": str, "snippet": str|None}
    """
    limit = max(1, min(int(limit), 10))

    r = requests.get(
        GOVUK_SEARCH,
        params={
            "keywords": query,
            "organisations[]": "uk-health-security-agency",
        },
        timeout=timeout,
        headers=UA,
    )
    if r.status_code != 200:
        return []

    soup = BeautifulSoup(r.text, "html.parser")

    # GOV.UK search results: anchor tags with result links
    urls: List[str] = []
    for a in soup.select("a[href]"):
        href = a.get("href") or ""
        # result links are usually relative like /government/publications/...
        if href.startswith("/government/") or href.startswith("/guidance/") or href.startswith("/health-and-social-care/") or href.startswith("/"):
            abs_url = urljoin("https://www.gov.uk", href)
            if abs_url.startswith("https://www.gov.uk/"):
                urls.append(abs_url)

    # de-dupe preserve order
    seen = set()
    ordered = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ordered.append(u)

    candidates: List[dict] = []
    for url in ordered[: max(limit * 4, 20)]:
        page = _fetch_govuk_snippet(url, timeout=timeout)
        title = page["title"] or "UKHSA / GOV.UK"
        snippet = page["snippet"]

        if not _looks_relevant(query, title, url):
            continue

        candidates.append({"title": title, "url": url, "snippet": snippet})
        if len(candidates) >= limit:
            break

    return candidates

def fetch_ukhsa_top(query: str, timeout: int = 12) -> dict | None:
    """
    Backwards-compatible: returns top UKHSA candidate (or None).
    Prefer using fetch_ukhsa_candidates() in the service.
    """
    cands = fetch_ukhsa_candidates(query, limit=1, timeout=timeout)
    return cands[0] if cands else None
