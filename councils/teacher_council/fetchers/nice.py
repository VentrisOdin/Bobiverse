from __future__ import annotations
import requests

NICE_SEARCH = "https://www.nice.org.uk/search"

def fetch_nice_top(query: str, timeout: int = 12) -> dict | None:
    try:
        r = requests.get(
            NICE_SEARCH,
            params={"q": query},
            timeout=timeout,
            headers={"User-Agent": "Bobiverse-TeacherCouncil/1.0"},
        )
        if r.status_code != 200:
            return None

        html = r.text
        import re

        # first search result card link
        m = re.search(r'href="(/guidance/[^"]+)"', html)
        if not m:
            m = re.search(r'href="(/[^"]+)"', html)
        if not m:
            return None

        path = m.group(1)
        url = "https://www.nice.org.uk" + path

        # Try to extract a title nearby
        tm = re.search(r'<h2[^>]*>\s*<a[^>]*href="' + re.escape(path) + r'[^"]*"[^>]*>([^<]+)</a>', html)
        title = (tm.group(1).strip() if tm else "NICE guidance/search result")

        return {"title": title, "url": url, "snippet": None}
    except Exception:
        return None
