

from __future__ import annotations

import re
import requests
from urllib.parse import quote
from typing import Optional, Dict, Any, List

OPENSEARCH = "https://en.wikipedia.org/w/api.php"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

_STOPWORDS = {
    "meaning", "define", "definition", "what", "is", "the", "a", "an", "of",
    "in", "for", "to", "and"
}

UA = {"User-Agent": "Bobiverse-TeacherCouncil/1.0"}


def _variants(query: str) -> List[str]:
    q = (query or "").strip()
    if not q:
        return []

    # original
    out = [q]

    # remove common definition words (MRSA meaning -> MRSA)
    toks = re.findall(r"[A-Za-z0-9]+", q)
    toks2 = [t for t in toks if t.lower() not in _STOPWORDS]
    if toks2:
        out.append(" ".join(toks2))

        # first strong token (often acronym)
        out.append(toks2[0])

    # de-dupe preserving order
    seen = set()
    uniq = []
    for v in out:
        v2 = v.strip()
        if v2 and v2.lower() not in seen:
            seen.add(v2.lower())
            uniq.append(v2)
    return uniq


def _try_summary_by_title(title: str, timeout: int) -> Optional[Dict[str, Any]]:
    title_slug = quote(title.replace(" ", "_"))
    url = SUMMARY.format(title=title_slug)
    r = requests.get(url, timeout=timeout, headers=UA)
    if r.status_code != 200:
        return None

    js = r.json()
    if js.get("type") == "disambiguation":
        return None
    extract = js.get("extract")
    page_url = js.get("content_urls", {}).get("desktop", {}).get("page")

    # Wikipedia REST sometimes returns a disambiguation stub; we still accept it if extract+url exist.
    if not extract or not page_url:
        return None

    return {
        "title": js.get("title") or title,
        "url": page_url,
        "snippet": extract.strip(),
    }


def fetch_wikipedia_summary(query: str, timeout: int = 12) -> dict | None:
    # Try multiple query variants
    for q in _variants(query):
        r = requests.get(
            OPENSEARCH,
            params={
                "action": "opensearch",
                "search": q,
                "limit": 5,
                "namespace": 0,
                "format": "json",
            },
            timeout=timeout,
            headers=UA,
        )
        if r.status_code != 200:
            continue

        data = r.json()
        titles = data[1] if len(data) > 1 else []
        if not titles:
            continue

        best_title = titles[0]
        out = _try_summary_by_title(best_title, timeout=timeout)
        if out:
            return out

    # Last-resort: try the first token directly as a title (helps acronyms)
    toks = re.findall(r"[A-Za-z0-9]+", (query or "").strip())
    if toks:
        out = _try_summary_by_title(toks[0], timeout=timeout)
        if out:
            return out

    return None
