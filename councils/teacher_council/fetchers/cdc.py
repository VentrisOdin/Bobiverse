from __future__ import annotations

import re
from typing import List, Optional
import requests

CDC_SEARCH = "https://search.cdc.gov/search/"
UA = {"User-Agent": "Bobiverse-TeacherCouncil/1.0"}

def _clean_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def fetch_cdc_candidates(query: str, limit: int = 3, timeout: int = 12) -> List[dict]:
    """
    Returns up to `limit` CDC candidates as:
      {"title": str, "url": str, "snippet": str | None}
    """
    limit = max(1, min(int(limit), 10))
    try:
        r = requests.get(
            CDC_SEARCH,
            params={
                "query": query,
                "sitelimit": "cdc.gov",
                "utf8": "✓",
            },
            timeout=timeout,
            headers=UA,
        )
        if r.status_code != 200 or not r.text:
            return []

        html = r.text

        # Grab multiple results. CDC search HTML commonly uses:
        # <a class="result-title" href="...">Title</a>
        # <p class="result-description">Snippet</p>
        titles = re.findall(r'<a class="result-title" href="([^"]+)">([^<]+)</a>', html)
        snippets = re.findall(r'<p class="result-description">(.+?)</p>', html, flags=re.S)

        out: List[dict] = []
        for i, (url, title) in enumerate(titles[:limit]):
            title = _clean_html(title)
            snippet = None
            if i < len(snippets):
                sn = _clean_html(snippets[i])
                snippet = sn[:800] if sn else None

            if url and title:
                out.append({"title": title, "url": url, "snippet": snippet})

        return out
    except Exception:
        return []

def fetch_cdc_top(query: str, timeout: int = 12) -> dict | None:
    cands = fetch_cdc_candidates(query, limit=1, timeout=timeout)
    return cands[0] if cands else None
