from __future__ import annotations
import requests
from urllib.parse import quote

# Uses CDC's site search endpoint (stable enough for v1)
CDC_SEARCH = "https://search.cdc.gov/search/"

def fetch_cdc_top(query: str, timeout: int = 12) -> dict | None:
    try:
        r = requests.get(
            CDC_SEARCH,
            params={
                "query": query,
                "sitelimit": "cdc.gov",
                "utf8": "✓",
            },
            timeout=timeout,
            headers={"User-Agent": "Bobiverse-TeacherCouncil/1.0"},
        )
        if r.status_code != 200:
            return None

        # very light parsing: grab first result link/title/snippet from the HTML
        html = r.text
        # crude but works for v1; can harden later
        import re
        m = re.search(r'<a class="result-title" href="([^"]+)">([^<]+)</a>', html)
        if not m:
            return None
        url = m.group(1)
        title = m.group(2).strip()

        sm = re.search(r'<p class="result-description">(.+?)</p>', html, re.S)
        snippet = ""
        if sm:
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", sm.group(1))).strip()

        if not url or not title:
            return None

        return {"title": title, "url": url, "snippet": snippet or None}
    except Exception:
        return None
