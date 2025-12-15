from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse


DEFAULT_ALLOWLIST = {
    "wikipedia.org",
    "arxiv.org",
    "ncbi.nlm.nih.gov",
    "nih.gov",
    "who.int",
    "gov.uk",
    "nhs.uk",
    "nist.gov",
    "developer.mozilla.org",
    "docs.python.org",
    "kubernetes.io",
    "github.com",
    "cdc.gov",
    "nice.org.uk",
    "ukhsa.gov.uk",
}

HIGH_TRUST = {
    "nih.gov",
    "ncbi.nlm.nih.gov",
    "who.int",
    "gov.uk",
    "nhs.uk",
    "nist.gov",
    "docs.python.org",
    "developer.mozilla.org",
    "kubernetes.io",
    "cdc.gov",
    "nice.org.uk",
    "ukhsa.gov.uk",
}

MEDIUM_TRUST = {
    "arxiv.org",
    "wikipedia.org",
    "github.com",
}


def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    host = host.lstrip("www.")

    # collapse common subdomains to base domains
    if host.endswith(".wikipedia.org"):
        return "wikipedia.org"
    if host.endswith(".nhs.uk"):
        return "nhs.uk"
    if host.endswith(".ncbi.nlm.nih.gov"):
        return "ncbi.nlm.nih.gov"

    return host


def is_allowed(url: str, allowlist: set[str]) -> bool:
    d = domain_of(url)
    return any(d == a or d.endswith("." + a) for a in allowlist)


def trust_for_domain(domain: str) -> str:
    if any(domain == d or domain.endswith("." + d) for d in HIGH_TRUST):
        return "high"
    if any(domain == d or domain.endswith("." + d) for d in MEDIUM_TRUST):
        return "medium"
    return "low"
