"""gosom/google-maps-scraper provider adapter - fixtures only, no network."""

import json

import pytest

from leadshoot.gmaps import (import_results, map_category, normalize_place,
                           parse_results)
from leadshoot.icp import ICP
from leadshoot.store import Store

# realistic gosom -json output (documented field names)
FIXTURE = [
    {
        "input_id": "restaurants in Brooklyn, New York",
        "link": "https://www.google.com/maps/place/?q=place_id:C1",
        "title": "Sal's Trattoria",
        "category": "Italian restaurant",
        "address": "212 Court St, Brooklyn, NY 11201",
        "website": "http://salstrattoria-example.com",
        "phone": "+1 718-555-0142",
        "review_count": 412,
        "review_rating": 4.7,
        "latitude": 40.6875,
        "longitude": -73.9927,
        "cid": "1111111111",
        "status": "Open",
        "emails": ["owner@salstrattoria-example.com"],
    },
    {
        "title": "Bushwick Fades",
        "category": "Barber shop",
        "address": "88 Knickerbocker Ave, Brooklyn, NY",
        "website": "",
        "phone": "+1 347-555-0199",
        "review_count": 9,
        "review_rating": 4.9,
        "latitude": 40.7041,
        "longitude": -73.9282,
        "cid": "2222222222",
        "status": "Open",
    },
    {
        "title": "Old Mill Diner",
        "category": "Diner",
        "address": "1 Mill Rd, Queens, NY",
        "cid": "3333333333",
        "status": "Permanently closed",
    },
    {
        "title": "Mystery Studio",
        "category": "Recording studio",
        "address": "5 Ave A, New York, NY",
        "cid": "4444444444",
        "status": "Open",
    },
]


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "gmaps.db")
    yield s
    s.close()


@pytest.fixture
def fixture_file(tmp_path):
    path = tmp_path / "results.json"
    path.write_text("\n".join(json.dumps(r) for r in FIXTURE))  # JSON lines
    return path


class TestParsing:
    def test_json_lines(self, fixture_file):
        assert len(parse_results(fixture_file)) == 4

    def test_json_array(self, tmp_path):
        p = tmp_path / "arr.json"
        p.write_text(json.dumps(FIXTURE))
        assert len(parse_results(p)) == 4

    def test_csv(self, tmp_path):
        p = tmp_path / "r.csv"
        p.write_text("title,category,address,cid,status,review_rating,review_count\n"
                     'Sal\'s,Italian restaurant,212 Court St,999,Open,4.5,100\n')
        recs = parse_results(p)
        assert recs[0]["title"] == "Sal's"

    def test_category_mapping(self):
        assert map_category("Italian restaurant", None) == "restaurant"
        assert map_category("Barber shop", None) == "salon"
        assert map_category("Coffee shop", None) == "cafe"
        assert map_category("Dental clinic", None) == "dentist"
        assert map_category("Recording studio", "restaurant") == "restaurant"
        assert map_category("Recording studio", None) == "recording_studio"

    def test_normalize_place(self):
        biz = normalize_place(FIXTURE[0], "Brooklyn, New York")
        assert biz["id"] == "g1111111111"
        assert biz["category"] == "restaurant"
        assert biz["osm_website"] == "http://salstrattoria-example.com"
        assert biz["phone"] == "+1 718-555-0142"
        # rule 01: harvested emails are refused
        assert biz["email"] is None
        # review aggregates become signals
        keys = {k for k, _, _ in biz["_signals"]}
        assert keys == {"reviews.rating", "reviews.count"}

    def test_permanently_closed_skipped(self):
        assert normalize_place(FIXTURE[2], "x") is None


class TestImport:
    def test_import_results(self, store, fixture_file):
        n = import_results(store, fixture_file, "Brooklyn, New York",
                           search_id=7)
        assert n == 3  # closed one skipped
        sal = store.get_business("g1111111111")
        assert sal["provider"] == "gmaps"
        assert sal["search_id"] == 7
        assert sal["reviews_rating"] == 4.7
        assert sal["reviews_count"] == 412
        assert sal["email"] is None
        barber = store.get_business("g2222222222")
        assert barber["category"] == "salon"

    def test_import_dedupes_by_cid(self, store, tmp_path):
        p = tmp_path / "dup.json"
        p.write_text("\n".join(json.dumps(FIXTURE[0]) for _ in range(3)))
        assert import_results(store, p, "x") == 1

    def test_icp_provider_validation(self):
        icp = ICP(name="g", area="Brooklyn, New York",
                  categories=["restaurant"], provider="gmaps")
        assert icp.to_dict()["provider"] == "gmaps"
        with pytest.raises(ValueError, match="provider"):
            ICP(name="b", area="x", categories=["cafe"], provider="bing")

    def test_gmaps_accepts_any_free_text_business_type(self):
        icp = ICP(name="g", area="Brooklyn",
                  categories=["recording studios", "commercial kitchens"],
                  provider="gmaps", mode="fit")
        assert icp.categories == ["recording_studios", "commercial_kitchens"]

    def test_review_signals_score_after_import(self, store, fixture_file):
        """Barber with 9 reviews -> few_reviews gap under reputation ICP."""
        from leadshoot.pipeline import apply_signal_update

        import_results(store, fixture_file, "Brooklyn, New York", search_id=1)
        icp = ICP(name="rep", area="Brooklyn, New York",
                  categories=["salon"], service="reputation_management",
                  prefer_established=False)
        store.save_icp("rep", icp.to_dict())
        biz = apply_signal_update(store, icp, "g2222222222")
        assert "few_reviews" in biz["gap_flags"]
        assert biz["score"] > 0
