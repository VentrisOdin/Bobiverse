
from __future__ import annotations

import re
from typing import List, Dict, Any, Optional
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup


def _searxng_search(query: str, max_results: int = 20, timeout: float = 10.0) -> List[Dict[str, str]]:
    """
    Local SearXNG JSON endpoint.
    Returns list of {title, url}.
    """
    base = "http://127.0.0.1:8888/search"
    params = {"q": query, "format": "json"}
    headers = {"User-Agent": "teacher-bob/1.0"}

    with httpx.Client(timeout=timeout, headers=headers) as client:
        r = client.get(base, params=params)
        r.raise_for_status()
        data = r.json()

    out: List[Dict[str, str]] = []
    for item in (data.get("results") or []):
        url = item.get("url") or ""
        title = _norm(item.get("title") or "")
        if not url or not title:
            continue
        content = _norm(item.get("content") or "")
        out.append({"title": title, "url": url, "snippet": content})
        if len(out) >= max_results:
            break
    return out


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().lstrip("www.")
    except Exception:
        return ""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _ddg_html_search(query: str, max_results: int = 20, timeout: float = 12.0) -> List[Dict[str, str]]:
    """
    DuckDuckGo HTML endpoint (no API key).
    Returns list of {title, url}.
    Robust to markup changes and basic bot-block pages.
    """
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/120.0",
        "Accept-Language": "en-GB,en;q=0.9",
    }

    with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
        r = client.get(url)
        r.raise_for_status()
        html = r.text or ""

    # If DDG is blocking / serving an interstitial, it often contains these hints
    lower = html.lower()
    if any(x in lower for x in ["unusual traffic", "automated requests", "verify you are a human", "captcha"]):
        return []

    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict[str, str]] = []

    # Primary selector (older DDG html)
    anchors = soup.select("a.result__a")

    # Fallbacks for markup variations
    if not anchors:
        anchors = soup.select("a[data-testid='result-title-a']")
    if not anchors:
        anchors = soup.select("a[href][class*='result__a']")
    if not anchors:
        # last resort: links inside result containers
        anchors = soup.select(".results a[href], .result a[href], .web-result a[href]")

    for a in anchors:
        href = a.get("href") or ""
        title = _norm(a.get_text(" "))

        if not href or not title:
            continue

        # Skip DDG internal links / junk
        if href.startswith("/") or "duckduckgo.com" in href:
            continue

        out.append({"title": title, "url": href})
        if len(out) >= max_results:
            break

    return out


def _fetch_html(url: str, timeout: float = 12.0) -> Optional[str]:
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/120.0"
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout, headers=headers) as client:
            r = client.get(url)
            if r.status_code >= 400:
                return None
            ctype = (r.headers.get("content-type") or "").lower()
            if "text/html" not in ctype and "application/xhtml" not in ctype:
                return None
            return r.text
    except Exception:
        return None


def _extract_snippet(html: str, max_chars: int = 650) -> str:
    soup = BeautifulSoup(html, "html.parser")

    # Remove high-noise elements
    for tag in soup(["script", "style", "nav", "header", "footer", "noscript", "aside"]):
        tag.decompose()

    # Prefer meta description if available
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        desc = _norm(meta["content"])
        if len(desc) >= 80:
            return desc[:max_chars]

    # Otherwise use first few paragraphs
    paras: List[str] = []
    for p in soup.find_all("p"):
        t = _norm(p.get_text(" "))
        if len(t) < 60:
            continue
        paras.append(t)
        if sum(len(x) for x in paras) > max_chars:
            break

    snip = _norm(" ".join(paras))
    if len(snip) > max_chars:
        snip = snip[:max_chars].rsplit(" ", 1)[0] + "…"
    return snip


def fetch_web_candidates(
    question: str,
    allowlist: Optional[List[str]] = None,
    limit: int = 5,
    search_k: int = 20,
) -> List[Dict[str, Any]]:
    """
    Search the web, then KEEP ONLY results whose domain is in allowlist.
    Returns candidates in the canonical format:
      {"title": str, "url": str, "snippet": str}
    """
    allow = set((d or "").lower().lstrip("www.") for d in (allowlist or []) if d)


    # Primary: local SearXNG JSON (stable). Fallback: DDG HTML scrape (best-effort).
    try:
        results = _searxng_search(question, max_results=search_k)
    except Exception:
        results = []

    if not results:
        results = _ddg_html_search(question, max_results=search_k)

    out: List[Dict[str, Any]] = []
    seen = set()


    for r in results:
        url = r.get("url") or ""
        title = r.get("title") or ""
        if not url or not title or url in seen:
            continue

        dom = _domain(url)
        if allow and not any(dom == a or dom.endswith("." + a) for a in allow):
            continue

        snippet = _norm(r.get("snippet") or "")
        if snippet and len(snippet) >= 60:
            out.append({"title": title, "url": url, "snippet": snippet})
            seen.add(url)
            if len(out) >= limit:
                break
            continue

        html = _fetch_html(url)
        if not html:
            continue

        snippet = _extract_snippet(html)
        if not snippet:
            continue

        out.append({"title": title, "url": url, "snippet": snippet})
        seen.add(url)

        if len(out) >= limit:
            break

    return out
