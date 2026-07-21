"""Optional gosom/google-maps-scraper provider (MIT, github.com/gosom/google-maps-scraper).

LeadShoot's default provider is OpenStreetMap - fully open data, no ToS
concerns. This module is the OPT-IN bridge for users who run gosom
themselves and accept that scraping Google Maps is against Google's terms
of service. LeadShoot never runs it silently: either the user imports a
results file they produced, or they explicitly configure the binary.

What we take from a gosom record: identity (title, address, phone,
website, lat/lon, category) plus review AGGREGATES (rating, count) which
land as ordinary LeadShoot signals with source=google. What we refuse:
the `emails` field - gosom harvests those from websites, and rule 01
(no email harvesting) applies to every provider.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .icp import CATEGORIES, normalize_category
from .store import K_RATING, K_REVIEW_COUNT, Store

TOS_NOTE = ("gmaps provider: you are running gosom/google-maps-scraper "
            "yourself; scraping Google Maps is against Google's ToS - "
            "your choice, your responsibility.")

# gosom free-text category -> LeadShoot category (contains-match, first wins)
_CONTAINS_MAP = [
    ("coffee", "cafe"), ("cafe", "cafe"), ("restaurant", "restaurant"),
    ("pizza", "restaurant"), ("burger", "restaurant"), ("diner", "restaurant"),
    ("takeout", "restaurant"), ("food", "restaurant"),
    ("hair", "salon"), ("nail", "salon"), ("beauty", "salon"),
    ("barber", "salon"), ("spa", "salon"),
    ("dental", "dentist"), ("dentist", "dentist"),
    ("doctor", "doctor"), ("medical clinic", "doctor"),
    ("veterinar", "vet"), ("pharmacy", "pharmacy"), ("optic", "optician"),
    ("auto repair", "car_repair"), ("car repair", "car_repair"),
    ("mechanic", "car_repair"), ("car dealer", "car_dealer"),
    ("plumb", "plumber"), ("electric", "electrician"), ("roof", "roofer"),
    ("carpent", "carpenter"), ("paint", "painter"), ("photo", "photographer"),
    ("law", "lawyer"), ("attorney", "lawyer"), ("account", "accountant"),
    ("insurance", "insurance"), ("real estate", "real_estate"),
    ("hotel", "hotel"), ("guest house", "hotel"),
    ("gym", "gym"), ("fitness", "gym"),
    ("bakery", "bakery"), ("bar", "bar"), ("pub", "bar"),
    ("florist", "florist"), ("pet", "pet"), ("laundry", "laundry"),
    ("dry clean", "laundry"), ("furniture", "furniture"),
    ("jewel", "jewelry"), ("butcher", "butcher"), ("book", "bookshop"),
    ("tattoo", "tattoo"),
]


def map_category(gmaps_category: str | None, fallback: str | None) -> str:
    text = (gmaps_category or "").strip().lower()
    if text:
        direct = normalize_category(text)
        if direct in CATEGORIES:
            return direct
        for needle, cat in _CONTAINS_MAP:
            if needle in text:
                return cat
    if fallback:
        return fallback
    return text.replace(" ", "_") or "unknown"


def _record_id(rec: dict) -> str:
    for key in ("cid", "place_id", "data_id"):
        v = str(rec.get(key) or "").strip()
        if v:
            return f"g{v}"
    basis = f"{rec.get('title','')}|{rec.get('address','')}"
    return "g" + hashlib.sha1(basis.encode()).hexdigest()[:16]


def _to_float(v) -> float | None:
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return None


def normalize_place(rec: dict, area: str,
                    fallback_category: str | None = None) -> dict | None:
    """One gosom record -> LeadShoot business dict (+ _signals sidecar)."""
    name = str(rec.get("title") or "").strip()
    if not name:
        return None
    status = str(rec.get("status") or "").lower()
    if "permanently closed" in status:
        return None
    website = str(rec.get("website") or "").strip() or None
    biz = {
        "id": _record_id(rec),
        "name": name,
        "category": map_category(rec.get("category"), fallback_category),
        "osm_tags": f"gmaps_category={rec.get('category','')}",
        "phone": str(rec.get("phone") or "").strip() or None,
        # rule 01: gosom's `emails` field is harvested from websites - refused.
        "email": None,
        "address": str(rec.get("address") or "").strip() or None,
        "lat": _to_float(rec.get("latitude")),
        "lon": _to_float(rec.get("longitude")),
        "osm_website": website,
        "area": area,
    }
    signals = []
    rating = _to_float(rec.get("review_rating"))
    count = _to_float(rec.get("review_count"))
    link = str(rec.get("link") or "").strip() or None
    if rating:
        signals.append((K_RATING, rating, link))
    if count is not None and (rating or count > 0):
        signals.append((K_REVIEW_COUNT, count, link))
    biz["_signals"] = signals
    return biz


def parse_results(path: str | Path) -> list[dict]:
    """Read a gosom results file: JSON lines, a JSON array, or CSV."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return []
    if path.suffix.lower() == ".csv" or (text[0] not in "[{"):
        return list(csv.DictReader(text.splitlines()))
    if text[0] == "[":
        return json.loads(text)
    records = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def import_results(store: Store, path: str | Path, area: str,
                   search_id: int | None = None,
                   fallback_category: str | None = None,
                   exclude_chains: bool = False) -> int:
    """Ingest a gosom results file. Returns businesses imported.

    Review aggregates ride along as ordinary signals (source=google).
    """
    count = 0
    seen: set[str] = set()
    for rec in parse_results(path):
        biz = normalize_place(rec, area, fallback_category)
        if biz is None or biz["id"] in seen:
            continue
        seen.add(biz["id"])
        signals = biz.pop("_signals")
        store.upsert_business(biz, search_id=search_id, provider="gmaps")
        for key, value, url in signals:
            store.add_signal(biz["id"], key, "google", value=value, url=url)
        count += 1
    store.conn.commit()
    return count


def find_binary(store: Store) -> str | None:
    configured = store.get_setting("gosom_binary")
    if configured and Path(configured).exists():
        return configured
    return shutil.which("google-maps-scraper")


def run_scrape(store: Store, area: str, categories: list[str],
               progress=None) -> Path:
    """Run the user's own gosom binary for `<category> in <area>` queries.

    Raises RuntimeError with setup instructions when gosom isn't available.
    """
    binary = find_binary(store)
    if not binary:
        raise RuntimeError(
            "gmaps provider needs gosom/google-maps-scraper. Either:\n"
            "  1) install it and `leadshoot config gosom_binary /path/to/binary`\n"
            "  2) or run it yourself (CLI/docker/web UI) and import the file:\n"
            "     leadshoot import-gmaps results.json --icp NAME\n"
            "Project: https://github.com/gosom/google-maps-scraper (MIT)."
        )
    if progress:
        progress(TOS_NOTE)
    depth = int(store.get_setting("gosom_depth", "3") or 3)
    workdir = Path(tempfile.mkdtemp(prefix="leadshoot-gmaps-"))
    queries = workdir / "queries.txt"
    results = workdir / "results.json"
    queries.write_text(
        "\n".join(f"{c.replace('_', ' ')} in {area}" for c in categories))
    cmd = [binary, "-input", str(queries), "-results", str(results),
           "-json", "-depth", str(depth), "-exit-on-inactivity", "3m"]
    if progress:
        progress(f"running gosom ({len(categories)} queries, depth {depth}) …")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if proc.returncode != 0 and not results.exists():
        raise RuntimeError(f"gosom failed: {proc.stderr[-500:]}")
    return results
