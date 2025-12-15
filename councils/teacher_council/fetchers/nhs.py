from __future__ import annotations
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

# NHS uses a standard site search endpoint
NHS_SEARCH = "https://www.nhs.uk/search/"

def fetch_nhs_top(query: str, timeout: int = 15) -> dict | None:
    r = requests.get(
        NHS_SEARCH,
        params={"q": query},
        timeout=timeout,
        headers={"User-Agent": "Bobiverse-TeacherCouncil/1.0"},
    )
    if r.status_code != 200:
        return None

    soup = BeautifulSoup(r.text, "html.parser")
    # NHS search results: first result link usually in an <a> with href
    first = soup.select_one("a.nhsuk-list-panel__link, a.nhsuk-card__link, a[href^='/conditions/']")
    if not first:
        # fallback: any result link
        first = soup.select_one("main a[href^='/']")

    if not first or not first.get("href"):
        return None

    href = first["href"]
    if href.startswith("/"):
        url = "https://www.nhs.uk" + href
    else:
        url = href

    # fetch the page and grab a short snippet
    r2 = requests.get(url, timeout=timeout, headers={"User-Agent": "Bobiverse-TeacherCouncil/1.0"})
    if r2.status_code != 200:
        return {"title": "NHS (search result)", "url": url, "snippet": None}

    soup2 = BeautifulSoup(r2.text, "html.parser")
    title = (soup2.select_one("h1") or soup2.title)
    title_text = title.get_text(strip=True) if title else "NHS"

    # first paragraph in article/main as snippet
    p = soup2.select_one("main p")
    snippet = p.get_text(" ", strip=True)[:800] if p else None

    return {"title": title_text, "url": url, "snippet": snippet}
