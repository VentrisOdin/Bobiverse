from __future__ import annotations

import re
from typing import List, Dict, Any
from xml.etree import ElementTree as ET

import requests

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

_UA = {"User-Agent": "Bobiverse-TeacherCouncil/1.0"}
_STOP = {"meaning", "define", "definition", "what", "is", "the", "a", "an", "of", "in", "for", "to", "and"}


def _clean(s: str) -> str:
    s = (s or "").strip()
    return re.sub(r"\s+", " ", s)


def _core_terms(q: str, max_terms: int = 3) -> List[str]:
    toks = [t.lower() for t in re.findall(r"[A-Za-z0-9]+", q or "")]
    toks = [t for t in toks if t not in _STOP and len(t) > 1]
    return toks[:max_terms] if toks else [q]


def _best_snippet_from_esummary(rec: Dict[str, Any]) -> str:
    source = _clean(rec.get("source") or "PubMed")
    pubdate = _clean(rec.get("pubdate") or "")
    m = re.search(r"\b(19|20)\d{2}\b", pubdate)
    year = m.group(0) if m else ""
    authors = rec.get("authors") or []
    first_author = _clean(authors[0].get("name")) if authors else ""
    parts = [p for p in [source, year, first_author] if p]
    return " • ".join(parts) if parts else source


def _try_fetch_abstract(pmids: List[str], timeout: int) -> Dict[str, str]:
    if not pmids:
        return {}

    try:
        r = requests.get(
            EFETCH,
            params={"db": "pubmed", "id": ",".join(pmids), "retmode": "xml", "rettype": "abstract"},
            timeout=timeout,
            headers=_UA,
        )
        if r.status_code != 200 or not r.text:
            return {}

        root = ET.fromstring(r.text)
        out: Dict[str, str] = {}

        for article in root.findall(".//PubmedArticle"):
            pmid_el = article.find(".//MedlineCitation/PMID")
            if pmid_el is None or not pmid_el.text:
                continue
            pmid = pmid_el.text.strip()

            parts: List[str] = []
            for abst in article.findall(".//Article/Abstract/AbstractText"):
                if abst.text and abst.text.strip():
                    parts.append(abst.text.strip())

            if parts:
                out[pmid] = _clean(" ".join(parts))

        return out
    except Exception:
        return {}


def fetch_pubmed_candidates(query: str, limit: int = 3, timeout: int = 15) -> List[dict]:
    """
    Returns up to `limit` PubMed candidates as:
      {"title": str, "url": str, "snippet": str}
    """
    limit = max(1, min(int(limit), 10))

    terms = _core_terms(query, max_terms=3)
    term = " ".join(terms)

    r = requests.get(
        ESEARCH,
        params={
            "db": "pubmed",
            "term": f'("{term}"[Title/Abstract]) OR ("{term}"[Title])',
            "retmode": "json",
            "retmax": limit,
        },
        timeout=timeout,
        headers=_UA,
    )
    if r.status_code != 200:
        return []

    js = r.json()
    pmids: List[str] = (js.get("esearchresult", {}).get("idlist", []) or [])
    pmids = [p for p in pmids if p]
    if not pmids:
        return []

    r2 = requests.get(
        ESUMMARY,
        params={"db": "pubmed", "id": ",".join(pmids), "retmode": "json"},
        timeout=timeout,
        headers=_UA,
    )
    if r2.status_code != 200:
        return []

    js2 = r2.json()
    result = js2.get("result", {}) or {}

    abstracts = _try_fetch_abstract(pmids, timeout=timeout)

    candidates: List[dict] = []
    for pmid in pmids:
        rec = result.get(pmid)
        if not rec:
            continue

        title = _clean(rec.get("title") or "") or f"PubMed {pmid}"
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

        abstract = abstracts.get(pmid, "")
        snippet = _clean(abstract) if abstract else _best_snippet_from_esummary(rec)

        candidates.append({"title": title, "url": url, "snippet": snippet})

    return candidates
