from __future__ import annotations
import requests
import xml.etree.ElementTree as ET

ARXIV_API = "http://export.arxiv.org/api/query"


def fetch_arxiv_top(query: str, timeout: int = 15) -> dict | None:
    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": 1,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    r = requests.get(ARXIV_API, params=params, timeout=timeout, headers={"User-Agent": "Bobiverse-TeacherCouncil/1.0"})
    if r.status_code != 200:
        return None

    # Parse Atom XML
    root = ET.fromstring(r.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    entry = root.find("atom:entry", ns)
    if entry is None:
        return None

    title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
    summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
    link = None
    for l in entry.findall("atom:link", ns):
        if l.attrib.get("rel") == "alternate" and "href" in l.attrib:
            link = l.attrib["href"]
            break

    if not title or not link:
        return None

    return {"title": title, "url": link, "snippet": summary[:800].strip()}
