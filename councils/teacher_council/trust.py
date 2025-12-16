from __future__ import annotations
from urllib.parse import urlparse

# -------------------------
# Allowlist (who can be accessed at all)
# -------------------------

DEFAULT_ALLOWLIST = {
    # Medical & public health
    "nhs.uk",
    "gov.uk",
    "cdc.gov",
    "who.int",
    "nih.gov",
    "nice.org.uk",
    "ukhsa.gov.uk",
    "nist.gov",

    # Research & literature
    "ncbi.nlm.nih.gov",
    "arxiv.org",

    # Reference / engineering
    "wikipedia.org",
    "developer.mozilla.org",
    "docs.python.org",
    "kubernetes.io",
    "github.com",
}

# -------------------------
# Trust tiers
# -------------------------

HIGH_TRUST = {
    # Authoritative medical / governmental guidance
    "nhs.uk",
    "gov.uk",
    "cdc.gov",
    "who.int",
    "nih.gov",
    "nice.org.uk",
    "ukhsa.gov.uk",
    "nist.gov",

    # Official technical documentation
    "docs.python.org",
    "developer.mozilla.org",
    "kubernetes.io",
}

MEDIUM_TRUST = {
    # Peer-reviewed but contextual / non-guideline
    "ncbi.nlm.nih.gov",   # PubMed abstracts, literature summaries
    "arxiv.org",

    # Community / reference
    "wikipedia.org",
    "github.com",
}

# -------------------------
# Helpers
# -------------------------

def domain_of(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    host = host.lstrip("www.")

    # Collapse known subdomains
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
