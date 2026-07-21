"""Roster ingest from OpenStreetMap.

Politeness contract (see README):
  - Nominatim: one geocode per area, cached forever in the DB, identifiable UA.
  - Overpass: small ad-hoc queries, 1s pause between them, backoff on 429/504.
    Users doing large/repeated ingests should set the `overpass_url` setting to
    a self-hosted instance.
"""

from __future__ import annotations

import time

import httpx

from . import __version__
from .store import Store

DEFAULT_OVERPASS = "https://overpass-api.de/api/interpreter"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

WEBSITE_KEYS = ("website", "contact:website", "url", "website:en", "contact:url")
PHONE_KEYS = ("phone", "contact:phone", "contact:mobile")
EMAIL_KEYS = ("email", "contact:email")


def user_agent(store: Store) -> str:
    contact = store.get_setting("contact", "https://github.com/moasq/leadshoot")
    return f"LeadShoot/{__version__} (+{contact})"


def pick_geocode(results: list[dict]) -> dict:
    """Prefer the candidate with the largest bounding box: real boundary
    polygons beat point-nodes whose default box is ~100m and would make a
    neighborhood search return nothing."""
    def bbox_area(r: dict) -> float:
        s, n, w, e = (float(x) for x in r["boundingbox"])
        return abs(n - s) * abs(e - w)

    return max(results, key=bbox_area)


def geocode_area(store: Store, area: str) -> tuple[float, float, float, float]:
    """Resolve an area name to (south, west, north, east). Cached in the DB."""
    cached = store.get_area(area)
    if cached:
        return cached
    resp = httpx.get(
        NOMINATIM,
        params={"q": area, "format": "json", "limit": 5},
        headers={"User-Agent": user_agent(store)},
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise ValueError(f"area not found: {area!r}")
    s, n, w, e = (float(x) for x in pick_geocode(results)["boundingbox"])
    bbox = (s, w, n, e)
    store.save_area(area, bbox)
    return bbox


def overpass_query(
    store: Store,
    bbox: tuple[float, float, float, float],
    selector: str,
    retries: int = 3,
) -> list[dict]:
    s, w, n, e = bbox
    q = (
        f"[out:json][timeout:60];"
        f"(node{selector}({s},{w},{n},{e});"
        f"way{selector}({s},{w},{n},{e}););"
        f"out tags center;"
    )
    url = store.get_setting("overpass_url", DEFAULT_OVERPASS)
    delay = 5.0
    for attempt in range(retries):
        resp = httpx.post(
            url,
            data={"data": q},
            headers={"User-Agent": user_agent(store)},
            timeout=90,
        )
        if resp.status_code in (429, 504):
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            # busy public server: degrade to a partial roster, don't crash
            # the whole search. The caller surfaces the warning.
            raise OverpassBusy(f"Overpass {resp.status_code} after "
                               f"{retries} attempts for {selector}")
        resp.raise_for_status()
        return resp.json().get("elements", [])
    return []


class OverpassBusy(RuntimeError):
    """Public Overpass mirror overloaded after all retries."""


def first_tag(tags: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        v = tags.get(k, "").strip()
        if v:
            return v
    return None


def build_address(tags: dict) -> str | None:
    parts = [
        tags.get("addr:housenumber"),
        tags.get("addr:street"),
        tags.get("addr:city"),
        tags.get("addr:postcode"),
    ]
    joined = " ".join(p for p in parts if p)
    return joined or None


def normalize_element(el: dict, category: str, area: str) -> dict | None:
    tags = el.get("tags", {})
    name = tags.get("name", "").strip()
    if not name:
        return None
    if el["type"] == "node":
        lat, lon = el.get("lat"), el.get("lon")
    else:
        center = el.get("center", {})
        lat, lon = center.get("lat"), center.get("lon")
    return {
        "id": f"{el['type'][0]}{el['id']}",
        "name": name,
        "category": category,
        "osm_tags": ";".join(f"{k}={v}" for k, v in sorted(tags.items())
                             if k in ("amenity", "shop", "craft", "office",
                                      "healthcare", "tourism", "leisure",
                                      "brand")),
        "phone": first_tag(tags, PHONE_KEYS),
        "email": first_tag(tags, EMAIL_KEYS),
        "address": build_address(tags),
        "lat": lat,
        "lon": lon,
        "osm_website": first_tag(tags, WEBSITE_KEYS),
        "area": area,
        "_is_chain": "brand" in tags or "brand:wikidata" in tags,
    }


def ingest(store: Store, area: str, categories: list[str],
           selectors: list[tuple[str, str]], exclude_chains: bool = True,
           search_id: int | None = None, progress=None) -> int:
    """Pull the roster for an area and upsert it. Returns businesses ingested.

    Every business found is stamped with search_id: the newest search claims
    the location (no duplication - the OSM id stays the primary key).
    """
    bbox = geocode_area(store, area)
    seen: set[str] = set()
    count = 0
    skipped: list[str] = []
    for i, (category, selector) in enumerate(selectors):
        if progress:
            progress(f"querying {category} ({selector})")
        try:
            elements = overpass_query(store, bbox, selector)
        except OverpassBusy:
            skipped.append(f"{category} {selector}")
            if progress:
                progress(f"⚠ Overpass busy - skipped {selector}; roster is "
                         f"partial (retry later or set overpass_url)")
            continue
        for el in elements:
            biz = normalize_element(el, category, area)
            if biz is None or biz["id"] in seen:
                continue
            seen.add(biz["id"])
            if exclude_chains and biz["_is_chain"]:
                continue
            biz.pop("_is_chain")
            store.upsert_business(biz, search_id=search_id)
            count += 1
        store.conn.commit()
        if i < len(selectors) - 1:
            time.sleep(1.0)
    return count
