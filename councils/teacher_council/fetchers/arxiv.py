from __future__ import annotations

import re
from typing import List, Dict, Any, Optional
import requests
import xml.etree.ElementTree as ET

ARXIV_API = "http://export.arxiv.org/api/query"
UA = {"User-Agent": "Bobiverse-TeacherCouncil/1.0"}

_STOP = {"meaning","define","definition","what","is","the","a","an","of","in","for","to","and"}

def _core_terms(q: str, max_terms: int = 3) -> List[str]:
    toks = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", q or "")]
    toks = [t for t in toks if t not in _STOP and len(t) > 1]
    return toks[:max_terms] if toks else [q]

def _is_definition_query(q: str) -> bool:
    ql = (q or "").lower()
    return any(k in ql for k in ["what is", "meaning", "define", "definition"])

def _parse_feed(xml_text: str) -> List[dict]:
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    out: List[dict] = []

    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
        summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        link = None
        for l in entry.findall("atom:link", ns):
            if l.attrib.get("rel") == "alternate" and "href" in l.attrib:
                link = l.attrib["href"]
                break
        if not title or not link:
            continue
        out.append({"title": title, "url": link, "snippet": summary[:800].strip()})
    return out

def fetch_arxiv_candidates(query: str, limit: int = 3, timeout: int = 15) -> List[dict]:
    """
    Returns up to `limit` arXiv candidates as:
      {"title": str, "url": str, "snippet": str}
    """
    limit = max(1, min(int(limit), 10))
    terms = _core_terms(query)
    term = " ".join(terms)

    # For definition-style questions, avoid "all:" (too broad).
    # Prefer title matches first; fall back to all: if nothing returns.
    if _is_definition_query(query):
        search_query = f'ti:"{term}" OR ti:{terms[0]}'
    else:
        search_query = f'all:"{term}" OR all:{terms[0]}'

    r = requests.get(
        ARXIV_API,
        params={
            "search_query": search_query,
            "start": 0,
            "max_results": max(limit, 5),  # grab a few so your ranker can choose
            "sortBy": "relevance",
            "sortOrder": "descending",
        },
        timeout=timeout,
        headers=UA,
    )
    if r.status_code != 200 or not r.text:
        return []

    cands = _parse_feed(r.text)
    if cands:
        return cands[:limit]

    # Fallback: broaden if definition query yielded nothing
    if _is_definition_query(query):
        r2 = requests.get(
            ARXIV_API,
            params={
                "search_query": f'all:"{term}" OR all:{terms[0]}',
                "start": 0,
                "max_results": max(limit, 5),
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
            timeout=timeout,
            headers=UA,
        )
        if r2.status_code != 200 or not r2.text:
            return []
        return _parse_feed(r2.text)[:limit]

    return []

def fetch_arxiv_top(query: str, timeout: int = 15) -> dict | None:
    c = fetch_arxiv_candidates(query, limit=1, timeout=timeout)
    return c[0] if c else None
