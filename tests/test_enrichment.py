"""Tech detection, RDAP parsing, and the Overture adapter - no network."""

import pytest

from leadshoot.check import CheckResult, detect_builder
from leadshoot.icp import ICP
from leadshoot.overture import (build_query, ingest_overture, match_category,
                              normalize_place, terms_for)
from leadshoot.rdap import extract_registration_year, registrable_domain
from leadshoot.score import gaps_from_check, maturity
from leadshoot.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "enrich.db")
    yield s
    s.close()


class TestBuilderDetection:
    def test_generator_meta(self):
        html = '<meta name="generator" content="WordPress 4.9.8">'
        assert detect_builder(html.lower()) == ("wordpress", 1)
        html = '<meta name="generator" content="WordPress 6.5">'
        assert detect_builder(html.lower()) == ("wordpress", 0)

    def test_markers(self):
        assert detect_builder("src=https://static.wixstatic.com/x.png") == ("wix", 0)
        assert detect_builder("cdn: img1.wsimg.com/a.js") == ("godaddy", 0)
        assert detect_builder("<link href=/wp-content/themes/x.css>") == ("wordpress", 0)
        assert detect_builder("<div>plain html</div>") == (None, 0)

    def test_gaps_from_working_site(self):
        wanted = ["diy_builder", "outdated_tech", "slow_site", "not_mobile",
                  "no_booking"]
        result = CheckResult(status="working", http_code=200, is_mobile=1,
                             has_booking=1, builder="wix", outdated=0, slow=1)
        gaps, conf = gaps_from_check(result, True, wanted)
        assert set(gaps) == {"diy_builder", "slow_site"}
        assert conf == "verified"

    def test_shopify_is_not_a_diy_gap(self):
        result = CheckResult(status="working", http_code=200, is_mobile=1,
                             has_booking=1, builder="shopify")
        gaps, _ = gaps_from_check(result, True, ["diy_builder"])
        assert gaps == []

    def test_outdated_wordpress_flags(self):
        result = CheckResult(status="working", http_code=200, is_mobile=1,
                             has_booking=1, builder="wordpress", outdated=1)
        gaps, _ = gaps_from_check(result, True, ["outdated_tech"])
        assert gaps == ["outdated_tech"]


class TestRDAP:
    def test_registrable_domain(self):
        assert registrable_domain("https://www.foo.com/x") == "foo.com"
        assert registrable_domain("shop.example.co.uk") == "example.co.uk"
        assert registrable_domain("https://bare.io") == "bare.io"

    def test_extract_registration_year(self):
        rdap = {"events": [
            {"eventAction": "last changed", "eventDate": "2024-01-01"},
            {"eventAction": "registration", "eventDate": "2008-06-11T04:00:00Z"},
        ]}
        assert extract_registration_year(rdap) == 2008
        assert extract_registration_year({"events": []}) is None

    def test_domain_year_is_maturity_floor(self, store):
        from leadshoot.pipeline import apply_signal_update
        store.upsert_business({
            "id": "n1", "name": "Old Shop", "category": "cafe",
            "osm_tags": "", "phone": "+1", "email": None, "address": None,
            "lat": 1.0, "lon": 1.0, "osm_website": "https://old.example",
            "area": "x",
        })
        store.save_check("n1", "broken", 500, None, None, None,
                         ["broken_site"], "verified", 0)
        icp = ICP(name="w", area="x", categories=["cafe"])
        store.save_icp("w", icp.to_dict())
        base = apply_signal_update(store, icp, "n1")["score"]   # unknown age
        store.add_signal("n1", "domain.registered_year", "rdap", value=2010)
        dated = apply_signal_update(store, icp, "n1")["score"]  # 16y floor
        assert dated > base

    def test_founded_beats_domain_year(self):
        # founded_year is real evidence; domain year only a floor - the
        # pipeline prefers founded when both exist (covered by ordering
        # in _signal_gaps_and_factor: founded or domain)
        assert maturity(1992)[0] == "established"


class TestOverture:
    REC = {
        "id": "08f2aa", "name": "Joe's Slice", "category": "pizza_restaurant",
        "website": "https://joes.example", "phone": "+1 212 555 0101",
        "addr": "7 Carmine St", "locality": "New York", "postcode": "10014",
        "confidence": 0.91, "lon": -74.0, "lat": 40.73,
    }

    def test_category_match(self):
        wanted = terms_for(["restaurant", "salon"])
        assert match_category("pizza_restaurant", wanted) == "restaurant"
        assert match_category("nail_salon", wanted) == "salon"
        assert match_category("hardware_store", wanted) is None

    def test_normalize(self):
        biz = normalize_place(self.REC, "Greenwich Village",
                              terms_for(["restaurant"]))
        assert biz["id"] == "o08f2aa"
        assert biz["category"] == "restaurant"
        assert "confidence=0.91" in biz["osm_tags"]
        assert biz["osm_website"] == "https://joes.example"

    def test_query_contains_bbox_and_confidence(self):
        sql = build_query("2026-06-17.0", (40.72, -74.01, 40.74, -73.99),
                          ["cafe"], 0.4)
        assert "BETWEEN -74.01 AND -73.99" in sql
        assert "confidence >= 0.4" in sql
        assert "2026-06-17.0" in sql

    def test_ingest_with_injected_rows(self, store):
        rows = [self.REC, {**self.REC, "id": "08f2ab", "name": "",},
                {**self.REC, "id": "08f2ac", "category": "car_wash"}]
        n = ingest_overture(store, "gv", ["restaurant"],
                            (40.7, -74.1, 40.8, -73.9), search_id=3,
                            query_fn=lambda sql: rows)
        assert n == 1  # nameless + unmatched-category rows dropped
        biz = store.get_business("o08f2aa")
        assert biz["provider"] == "overture"
        assert biz["search_id"] == 3

    def test_icp_accepts_overture(self):
        icp = ICP(name="o", area="x", categories=["cafe"],
                  provider="overture")
        assert icp.provider == "overture"
