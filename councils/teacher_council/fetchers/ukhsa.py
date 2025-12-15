from __future__ import annotations
import requests

UKHSA_SEARCH = "https://ukhsa.blog.gov.uk/"

def fetch_ukhsa_top(query: str, timeout: int = 12) -> dict | None:
    """
    v1: UKHSA doesn't have a super clean public search endpoint everywhere,
    so we use the blog.gov.uk search (good enough for initial public health hits).
    """
    try:
        r = requests.get(
            "https://www.gov.uk/search/all",
            params={
                "keywords": query,
                "organisations[]": "uk-health-security-agency",
            },
            timeout=timeout,
            headers={"User-Agent": "Bobiverse-TeacherCouncil/1.0"},
        )
        if r.status_code != 200:
            return None

        html = r.text
        import re

        m = re.search(r'href="(https://www\.gov\.uk/[^"]+)"', html)
        if not m:
            return None

        url = m.group(1)
        return {"title": "UKHSA / GOV.UK result", "url": url, "snippet": None}
    except Exception:
        return None
