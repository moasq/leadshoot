"""Overture Maps places provider - big open data, no scraping.

Overture (Linux Foundation; Meta/Microsoft/AWS/TomTom) publishes ~60M places
as GeoParquet on public S3 under CDLA-Permissive-2.0. DuckDB (MIT) queries
the release in place with HTTP range requests - no bulk download, no keys,
no ToS tension. This is the coverage upgrade that keeps the moat clean.

Optional dependency: pip install "leadshoot[overture]"  (duckdb).
"""

from __future__ import annotations

from .store import Store

DEFAULT_RELEASE = "2026-06-17.0"
S3_TEMPLATE = ("s3://overturemaps-us-west-2/release/{release}"
               "/theme=places/type=place/*")
ATTRIBUTION = "Places data © Overture Maps Foundation, CDLA-Permissive-2.0"

# LeadShoot category -> substrings matched against Overture's category slug
CATEGORY_TERMS: dict[str, list[str]] = {
    "restaurant": ["restaurant", "fast_food"],
    "cafe": ["cafe", "coffee"],
    "bar": ["bar", "pub"],
    "bakery": ["bakery"],
    "dentist": ["dentist", "dental"],
    "doctor": ["doctor", "physician", "medical_clinic"],
    "vet": ["veterinar"],
    "pharmacy": ["pharmacy"],
    "optician": ["optic", "eyewear"],
    "salon": ["salon", "barber", "beauty", "nail", "spa"],
    "barber": ["barber"],
    "tattoo": ["tattoo"],
    "gym": ["gym", "fitness"],
    "plumber": ["plumb"],
    "electrician": ["electric"],
    "roofer": ["roof"],
    "carpenter": ["carpent"],
    "painter": ["paint"],
    "photographer": ["photograph"],
    "car_repair": ["car_repair", "auto_repair", "automotive_repair",
                   "auto_service"],
    "car_dealer": ["car_dealer"],
    "florist": ["florist", "flower"],
    "pet": ["pet_store", "pet_groom"],
    "lawyer": ["lawyer", "attorney", "law_firm", "legal"],
    "accountant": ["accountant", "accounting", "bookkeep"],
    "insurance": ["insurance"],
    "real_estate": ["real_estate"],
    "hotel": ["hotel", "guest_house", "bed_and_breakfast"],
    "laundry": ["laundry", "dry_clean"],
    "furniture": ["furniture"],
    "jewelry": ["jewel"],
    "butcher": ["butcher", "meat_shop"],
    "greengrocer": ["grocer"],
    "bookshop": ["book_store", "bookstore"],
}


def terms_for(categories: list[str]) -> dict[str, list[str]]:
    return {c: CATEGORY_TERMS.get(c, [c]) for c in categories}


def match_category(overture_slug: str | None,
                   wanted: dict[str, list[str]]) -> str | None:
    slug = (overture_slug or "").lower()
    for ours, terms in wanted.items():
        if any(t in slug for t in terms):
            return ours
    return None


def build_query(release: str, bbox: tuple[float, float, float, float],
                categories: list[str], min_confidence: float) -> str:
    s, w, n, e = bbox
    likes = " OR ".join(
        f"categories.primary ILIKE '%{term}%'"
        for terms in terms_for(categories).values() for term in terms
    )
    return f"""
        SELECT id,
               names.primary       AS name,
               categories.primary  AS category,
               websites[1]         AS website,
               phones[1]           AS phone,
               addresses[1].freeform AS addr,
               addresses[1].locality AS locality,
               addresses[1].postcode AS postcode,
               confidence,
               bbox.xmin AS lon, bbox.ymin AS lat
        FROM read_parquet('{S3_TEMPLATE.format(release=release)}',
                          hive_partitioning=1)
        WHERE bbox.xmin BETWEEN {w} AND {e}
          AND bbox.ymin BETWEEN {s} AND {n}
          AND confidence >= {min_confidence}
          AND ({likes})
    """


def duckdb_rows(sql: str) -> list[dict]:
    try:
        import duckdb
    except ImportError:
        raise RuntimeError(
            "The overture provider needs DuckDB: "
            "pip install 'leadshoot[overture]'"
        )
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def normalize_place(rec: dict, area: str,
                    wanted: dict[str, list[str]]) -> dict | None:
    name = str(rec.get("name") or "").strip()
    if not name:
        return None
    category = match_category(rec.get("category"), wanted)
    if category is None:
        return None
    address = " ".join(str(p) for p in
                       (rec.get("addr"), rec.get("locality"),
                        rec.get("postcode")) if p) or None
    conf = rec.get("confidence")
    return {
        "id": f"o{rec['id']}",
        "name": name,
        "category": category,
        "osm_tags": (f"overture_category={rec.get('category', '')};"
                     f"confidence={conf:.2f}" if conf is not None else
                     f"overture_category={rec.get('category', '')}"),
        "phone": str(rec.get("phone") or "").strip() or None,
        "email": None,
        "address": address,
        "lat": rec.get("lat"),
        "lon": rec.get("lon"),
        "osm_website": str(rec.get("website") or "").strip() or None,
        "area": area,
    }


def ingest_overture(store: Store, area: str, categories: list[str],
                    bbox: tuple[float, float, float, float],
                    search_id: int | None = None,
                    progress=None, query_fn=None) -> int:
    """Pull the roster from the Overture release for this bbox."""
    release = store.get_setting("overture_release", DEFAULT_RELEASE)
    min_conf = float(store.get_setting("overture_min_confidence", "0.4"))
    if progress:
        progress(f"querying Overture {release} (min confidence {min_conf}) …")
    sql = build_query(release, bbox, categories, min_conf)
    rows = (query_fn or duckdb_rows)(sql)
    wanted = terms_for(categories)
    seen: set[str] = set()
    count = 0
    for rec in rows:
        biz = normalize_place(rec, area, wanted)
        if biz is None or biz["id"] in seen:
            continue
        seen.add(biz["id"])
        store.upsert_business(biz, search_id=search_id, provider="overture")
        count += 1
    store.conn.commit()
    return count
