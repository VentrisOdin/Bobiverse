from __future__ import annotations

import re
from typing import List, Dict, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

NICE_SEARCH = "https://www.nice.org.uk/search"
UA = {"User-Agent": "Bobiverse-TeacherCouncil/1.0"}

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

def _fetch_page_snippet(url: str, timeout: int) -> Dict[str, Optional[str]]:
    r = requests.get(url, timeout=timeout, headers=UA)
    if r.status_code != 200:
        return {"title": None, "snippet": None}

    soup = BeautifulSoup(r.text, "html.parser")

    # best-effort title
    h1 = soup.select_one("h1")
    title = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else None)

    # best-effort snippet: first meaningful paragraph in main/article
    p = soup.select_one("main p, article p, .page-content p")
    snippet = p.get_text(" ", strip=True) if p else None
    if snippet:
        snippet = snippet[:800]

    return {"title": title, "snippet": snippet}

def _extract_result_links(soup: BeautifulSoup) -> List[str]:
    links: List[str] = []

    # NICE search results often contain result cards with anchor tags.
    # We accept internal links and later relevance-filter them.
    for a in soup.select("main a[href], article a[href]"):
        href = a.get("href")
        if not href:
            continue
        # skip obvious junk
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        # keep NICE internal only
        abs_url = urljoin("https://www.nice.org.uk", href)
        if "nice.org.uk" not in abs_url:
            continue
        links.append(abs_url)

    # de-dupe, preserve order
    seen = set()
    out = []
    for u in links:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out

def fetch_nice_candidates(query: str, limit: int = 5, timeout: int = 12) -> List[dict]:
    """
    Returns up to `limit` relevant NICE candidates:
      {"title": str, "url": str, "snippet": str|None}
    """
    limit = max(1, min(int(limit), 10))

    r = requests.get(NICE_SEARCH, params={"q": query}, timeout=timeout, headers=UA)
    if r.status_code != 200:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    urls = _extract_result_links(soup)

    candidates: List[dict] = []
    # fetch a bit more, then filter down
    for url in urls[: max(limit * 4, 20)]:
        page = _fetch_page_snippet(url, timeout=timeout)
        title = page["title"] or "NICE"
        snippet = page["snippet"]

        # relevance on title+url (snippets can be generic)
        if not _looks_relevant(query, title, url):
            continue

        candidates.append({"title": title, "url": url, "snippet": snippet})
        if len(candidates) >= limit:
            break

    return candidates

def fetch_nice_top(query: str, timeout: int = 12) -> dict | None:
    """
    Backwards-compatible: returns top NICE candidate (or None).
    Prefer using fetch_nice_candidates() in the service.
    """
    cands = fetch_nice_candidates(query, limit=1, timeout=timeout)
    return cands[0] if cands else None
