from __future__ import annotations
import requests
from urllib.parse import quote

OPENSEARCH = "https://en.wikipedia.org/w/api.php"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

def fetch_wikipedia_summary(query: str, timeout: int = 12) -> dict | None:
    # Step 1: search for best-matching title
    r = requests.get(
        OPENSEARCH,
        params={
            "action": "opensearch",
            "search": query,
            "limit": 1,
            "namespace": 0,
            "format": "json",
        },
        timeout=timeout,
        headers={"User-Agent": "Bobiverse-TeacherCouncil/1.0"},
    )
    if r.status_code != 200:
        return None

    data = r.json()
    titles = data[1] if len(data) > 1 else []
    if not titles:
        return None

    best_title = titles[0]
    title_slug = quote(best_title.replace(" ", "_"))

    # Step 2: fetch summary
    url = SUMMARY.format(title=title_slug)
    r2 = requests.get(url, timeout=timeout, headers={"User-Agent": "Bobiverse-TeacherCouncil/1.0"})
    if r2.status_code != 200:
        return None

    js = r2.json()
    extract = js.get("extract")
    page_url = js.get("content_urls", {}).get("desktop", {}).get("page")

    if not extract or not page_url:
        return None

    return {"title": js.get("title") or best_title, "url": page_url, "snippet": extract.strip()}
