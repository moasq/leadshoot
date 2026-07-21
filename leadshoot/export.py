"""CSV / JSON export. Exports carry the ODbL attribution."""

from __future__ import annotations

import csv
import io
import json

from . import OSM_ATTRIBUTION

COLUMNS = [
    "id", "name", "category", "phone", "email", "address", "lat", "lon",
    "osm_website", "site_status", "gap_flags", "confidence", "score",
    "reviews_rating", "reviews_count", "reviews_sources",
    "social_followers", "social_last_post_days", "founded_year",
    "stage", "note", "checked_at", "search_id",
]


def to_csv(leads: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for lead in leads:
        writer.writerow(lead)
    return buf.getvalue()


def to_json(leads: list[dict]) -> str:
    return json.dumps(
        {
            "attribution": OSM_ATTRIBUTION,
            "count": len(leads),
            "leads": [{k: lead.get(k) for k in COLUMNS} for lead in leads],
        },
        indent=2,
        default=str,
    )
