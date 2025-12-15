from __future__ import annotations
import requests

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


def fetch_pubmed_top(query: str, timeout: int = 15) -> dict | None:
    # Search
    r = requests.get(
        ESEARCH,
        params={"db": "pubmed", "term": query, "retmode": "json", "retmax": 1},
        timeout=timeout,
        headers={"User-Agent": "Bobiverse-TeacherCouncil/1.0"},
    )
    if r.status_code != 200:
        return None
    js = r.json()
    ids = js.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return None
    pmid = ids[0]

    # Summary
    r2 = requests.get(
        ESUMMARY,
        params={"db": "pubmed", "id": pmid, "retmode": "json"},
        timeout=timeout,
        headers={"User-Agent": "Bobiverse-TeacherCouncil/1.0"},
    )
    if r2.status_code != 200:
        return None
    js2 = r2.json()
    rec = js2.get("result", {}).get(pmid)
    if not rec:
        return None

    title = (rec.get("title") or "").strip()
    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if not title:
        title = f"PubMed {pmid}"

    # PubMed summaries don’t always include abstract here; still valuable as citation
    snippet = (rec.get("source") or "PubMed").strip()
    return {"title": title, "url": url, "snippet": snippet}
