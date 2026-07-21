"""Domain age via RDAP - the open registration-data protocol (RFC 9082).

No API keys, no scraping: IANA publishes a bootstrap file mapping each TLD
to its registry's RDAP server, and registries answer JSON. A domain's
registration year is a *lower bound* for how long the business has existed -
LeadShoot's maturity qualifier uses it when the real founding year is unknown,
so "unknown age" leads become fairly ranked automatically.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import httpx

from .check import normalize_url
from .store import Store

IANA_BOOTSTRAP = "https://data.iana.org/rdap/dns.json"

# second-level public suffixes where the registrable domain has 3 labels
_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "or"}
_CC_WITH_SECOND = {"uk", "au", "nz", "br", "jp", "za", "in", "id", "il",
                   "kr", "om", "sa", "ae", "eg"}


def bootstrap_map(store: Store) -> dict[str, str]:
    """TLD -> RDAP base URL, cached in settings (refresh: delete the key)."""
    cached = store.get_setting("rdap_bootstrap")
    if cached:
        return json.loads(cached)
    resp = httpx.get(IANA_BOOTSTRAP, timeout=30)
    resp.raise_for_status()
    mapping: dict[str, str] = {}
    for tlds, urls in (
        (svc[0], svc[1]) for svc in resp.json().get("services", [])
    ):
        for tld in tlds:
            if urls:
                mapping[tld.lower()] = urls[0]
    store.set_setting("rdap_bootstrap", json.dumps(mapping))
    return mapping


def registrable_domain(url: str) -> str | None:
    host = urlsplit(normalize_url(url)).netloc.split(":")[0].lower()
    labels = [p for p in host.split(".") if p]
    if len(labels) < 2:
        return None
    if (len(labels) >= 3 and labels[-1] in _CC_WITH_SECOND
            and labels[-2] in _SECOND_LEVEL):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def registration_year(store: Store, url: str,
                      client: httpx.Client | None = None) -> tuple[int | None, str | None]:
    """(year, rdap_query_url) for the site's registrable domain."""
    domain = registrable_domain(url)
    if not domain:
        return None, None
    base = bootstrap_map(store).get(domain.rsplit(".", 1)[-1])
    if not base:
        return None, None
    query = f"{base.rstrip('/')}/domain/{domain}"
    try:
        own_client = client is None
        c = client or httpx.Client(follow_redirects=True)
        try:
            resp = c.get(query, timeout=15,
                         headers={"Accept": "application/rdap+json"})
        finally:
            if own_client:
                c.close()
        if resp.status_code != 200:
            return None, query
        return extract_registration_year(resp.json()), query
    except httpx.HTTPError:
        return None, query


def extract_registration_year(rdap: dict) -> int | None:
    for event in rdap.get("events", []):
        if event.get("eventAction") == "registration":
            date = str(event.get("eventDate", ""))
            if len(date) >= 4 and date[:4].isdigit():
                return int(date[:4])
    return None
