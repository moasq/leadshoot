"""Core engine tests - no network."""

import pytest

from leadshoot.check import (BLOCKED, BROKEN, NO_SITE, NO_SSL, PROTECTED,
                           UNREACHABLE, WORKING, CheckResult, classify_code,
                           extract_social_profiles, normalize_url, scan_html)
from leadshoot.icp import ICP, infer_gaps, normalize_category, selectors_for
from leadshoot.pipeline import apply_signal_update
from leadshoot.score import (UNVERIFIED, VERIFIED, candidate_gaps,
                           gaps_from_check, maturity, review_gaps, score,
                           social_gaps)
from leadshoot.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


BIZ = {
    "id": "n1", "name": "Rose City Dental", "category": "dentist",
    "osm_tags": "amenity=dentist", "phone": "+1-503-555-0100", "email": None,
    "address": "100 Main St Portland", "lat": 45.5, "lon": -122.6,
    "osm_website": "https://rosecity.example", "area": "portland, or",
}


# ---------- store: the facts-vs-workflow split ----------

class TestStore:
    def test_upsert_and_leads(self, store):
        store.upsert_business(BIZ)
        store.save_check("n1", "broken", 500, None, None, None,
                         ["broken_site"], "verified", 95)
        store.conn.commit()
        leads = store.leads()
        assert len(leads) == 1
        assert leads[0]["score"] == 95
        assert leads[0]["stage"] == "new"

    def test_reingest_never_clobbers_user_layer(self, store):
        store.upsert_business(BIZ)
        store.save_check("n1", "broken", 500, None, None, None,
                         ["broken_site"], "verified", 95)
        store.mark("n1", stage="contacted", note="left voicemail")
        # re-ingest (roster refresh) - the whole point of the split
        store.upsert_business({**BIZ, "name": "Rose City Dental LLC"})
        store.conn.commit()
        lead = store.leads(stage="contacted")[0]
        assert lead["name"] == "Rose City Dental LLC"   # fact refreshed
        assert lead["stage"] == "contacted"             # user layer intact
        assert lead["note"] == "left voicemail"
        # roster upsert must not clobber check results either
        assert lead["score"] == 95
        assert lead["gap_flags"] == "broken_site"

    def test_fresh_only_excludes_worked_leads(self, store):
        store.upsert_business(BIZ)
        store.upsert_business({**BIZ, "id": "n2", "name": "Other Dental"})
        store.save_check("n1", "broken", 500, None, None, None,
                         ["broken_site"], "verified", 95)
        store.save_check("n2", "broken", 500, None, None, None,
                         ["broken_site"], "verified", 90)
        store.mark("n1", stage="contacted")
        fresh = store.leads(fresh_only=True)
        assert [l["id"] for l in fresh] == ["n2"]

    def test_hidden_excluded_by_default(self, store):
        store.upsert_business(BIZ)
        store.mark("n1", stage="hidden")
        assert store.leads() == []
        assert len(store.leads(stage="hidden")) == 1

    def test_mark_unknown_business(self, store):
        assert store.mark("nope", stage="contacted") is False

    def test_mark_invalid_stage(self, store):
        store.upsert_business(BIZ)
        with pytest.raises(ValueError):
            store.mark("n1", stage="bogus")

    def test_icp_roundtrip(self, store):
        icp = ICP(name="t", area="Portland, OR", categories=["dentist"])
        store.save_icp("t", icp.to_dict())
        loaded = ICP.from_dict(store.get_icp("t"))
        assert loaded.area == "Portland, OR"
        assert loaded.weights == icp.weights

    def test_legacy_icp_numeric_filter_is_hidden(self, store):
        definition = ICP(
            name="legacy", area="Portland", categories=["dentist"]
        ).to_dict()
        definition["min_score"] = 60
        definition.pop("min_priority")
        store.save_icp("legacy", definition)
        loaded = store.get_icp("legacy")
        assert "min_score" not in loaded
        assert loaded["min_priority"] == "not_sure"

    def test_gap_filter_no_substring_collision(self, store):
        store.upsert_business(BIZ)
        store.save_check("n1", "working", 200, 1, 1, 0,
                         ["no_booking"], "verified", 35)
        store.conn.commit()
        # "no_booking" must not match a filter for "booking" or "no_b"
        assert store.leads(gap="no_booking")
        assert store.leads(gap="no_ssl") == []


# ---------- icp ----------

class TestICP:
    def test_aliases(self):
        assert normalize_category("Coffee Shop") == "cafe"
        assert normalize_category("restaurants") == "restaurant"

    def test_service_infers_gaps(self):
        icp = ICP(name="x", area="a", categories=["cafe"],
                  service="website_design")
        assert "broken_site" in icp.weights and "no_website" in icp.weights
        assert "not_mobile" not in icp.weights

    def test_unknown_category_rejected(self):
        with pytest.raises(ValueError, match="unknown categories"):
            ICP(name="x", area="a", categories=["spaceport"])

    def test_unknown_service_rejected(self):
        with pytest.raises(ValueError, match="unknown service"):
            ICP(name="x", area="a", categories=["cafe"], service="alchemy")

    def test_selectors(self):
        sels = selectors_for(["dentist"])
        assert ("dentist", '["amenity"="dentist"]') in sels

    def test_geocode_prefers_polygon_over_point(self):
        from leadshoot.ingest import pick_geocode
        point = {"boundingbox": ["40.7335", "40.7336", "-74.0028", "-74.0027"],
                 "type": "attraction"}
        polygon = {"boundingbox": ["40.72", "40.74", "-74.01", "-73.99"],
                   "type": "neighbourhood"}
        assert pick_geocode([point, polygon]) is polygon


# ---------- check (pure parts) ----------

class TestCheck:
    def test_normalize_url(self):
        assert normalize_url("example.com") == "https://example.com"
        assert normalize_url("http://x.com") == "http://x.com"

    def test_classify(self):
        assert classify_code(200) == WORKING
        assert classify_code(301) == WORKING  # follow_redirects handles these
        assert classify_code(404) == BROKEN
        assert classify_code(500) == BROKEN

    def test_bot_defense_is_not_broken(self):
        # a WAF answering 403/429 means the site is UP - never a lead
        assert classify_code(403) == PROTECTED
        assert classify_code(429) == PROTECTED
        assert classify_code(401) == PROTECTED

    def test_root_of_deep_links(self):
        from leadshoot.check import root_of
        assert root_of("https://x.com/locations/soho/") == "https://x.com/"
        assert root_of("https://x.com/menu?d=1") == "https://x.com/"
        assert root_of("https://x.com/") is None
        assert root_of("x.com") is None  # normalized to root already

    def test_scan_html(self):
        mobile, booking = scan_html(
            '<meta name="viewport" content="width=device-width"> Book now!')
        assert mobile == 1 and booking == 1
        mobile, booking = scan_html("<html><body>hello</body></html>")
        assert mobile == 0 and booking == 0

    def test_extracts_profiles_but_not_share_links(self):
        html = """
        <a href="https://instagram.com/example_salon/">Instagram</a>
        <a href="//facebook.com/example.salon">Facebook</a>
        <a href="https://facebook.com/sharer/sharer.php?u=x">Share</a>
        <a href="https://example.com/contact">Contact</a>
        """
        assert extract_social_profiles(html, "https://example.com") == [
            "https://instagram.com/example_salon/",
            "https://facebook.com/example.salon",
        ]


# ---------- gap derivation + scoring ----------

class TestScore:
    WANTED = ["no_website", "broken_site", "no_ssl", "not_mobile", "no_booking"]
    WEIGHTS = {"no_website": 0.9, "broken_site": 1.0, "no_ssl": 0.5,
               "not_mobile": 0.4, "no_booking": 0.3}

    def test_no_tag_is_unverified(self):
        gaps, conf = gaps_from_check(CheckResult(status="no_site_listed"),
                                     has_website_tag=False, wanted_gaps=self.WANTED)
        assert gaps == ["no_website"] and conf == UNVERIFIED

    def test_broken_is_verified(self):
        gaps, conf = gaps_from_check(CheckResult(status=BROKEN, http_code=500),
                                     has_website_tag=True, wanted_gaps=self.WANTED)
        assert gaps == ["broken_site"] and conf == VERIFIED

    def test_blocked_never_flagged(self):
        gaps, _ = gaps_from_check(CheckResult(status=BLOCKED),
                                  has_website_tag=True, wanted_gaps=self.WANTED)
        assert gaps == []

    def test_protected_never_flagged(self):
        gaps, _ = gaps_from_check(CheckResult(status=PROTECTED, http_code=403),
                                  has_website_tag=True, wanted_gaps=self.WANTED)
        assert gaps == []

    def test_unreachable_is_downgraded(self):
        gaps, conf = gaps_from_check(CheckResult(status=UNREACHABLE),
                                     has_website_tag=True, wanted_gaps=self.WANTED)
        assert gaps == ["broken_site"] and conf == UNVERIFIED

    def test_working_site_minor_gaps_only(self):
        gaps, _ = gaps_from_check(
            CheckResult(status=WORKING, http_code=200, is_mobile=0, has_booking=1),
            has_website_tag=True, wanted_gaps=self.WANTED)
        assert gaps == ["not_mobile"]

    def test_unwanted_gaps_filtered(self):
        gaps, _ = gaps_from_check(
            CheckResult(status=WORKING, http_code=200, is_mobile=0, has_booking=0),
            has_website_tag=True, wanted_gaps=["broken_site"])
        assert gaps == []

    def test_verified_outranks_unverified(self):
        broken = score(["broken_site"], self.WEIGHTS, has_phone=True)
        no_site = score(["no_website"], self.WEIGHTS, has_phone=True,
                        confidence=UNVERIFIED)
        assert broken > no_site

    def test_score_bounds(self):
        assert score([], self.WEIGHTS) == 0
        assert score(self.WANTED, self.WEIGHTS, has_phone=True) <= 100

    def test_more_gaps_score_higher(self):
        one = score(["no_ssl"], self.WEIGHTS)
        two = score(["no_ssl", "not_mobile"], self.WEIGHTS)
        assert two > one


# ---------- review signals ----------

class TestReviews:
    WANTED = ["weak_reviews", "few_reviews", "broken_site"]

    def test_no_signals_no_gaps(self):
        assert review_gaps(None, None, self.WANTED) == []

    def test_weak_reviews_needs_sample(self):
        # one angry review must not condemn a business
        assert review_gaps(1.0, 2, self.WANTED) == ["few_reviews"]
        assert "weak_reviews" in review_gaps(2.8, 20, self.WANTED)

    def test_good_reviews_no_gap(self):
        assert review_gaps(4.8, 200, self.WANTED) == []

    def test_few_reviews_threshold(self):
        assert review_gaps(4.5, 5, self.WANTED) == ["few_reviews"]
        assert review_gaps(4.5, 50, self.WANTED) == []

    def test_signal_roundtrip_and_summary(self, store):
        store.upsert_business(BIZ)
        assert store.add_review_signal("n1", "google", 4.0, 100) is True
        assert store.add_review_signal("n1", "yelp", 2.0, 50) is True
        rating, total = store.review_summary("n1")
        assert total == 150
        assert rating == pytest.approx(3.33, abs=0.01)  # count-weighted
        assert store.add_review_signal("nope", "google", 4.0, 10) is False

    def test_apply_signal_update_rescores(self, store):
        store.upsert_business(BIZ)
        store.save_check("n1", "working", 200, 1, 1, 1, [], "", 0)
        store.conn.commit()
        icp = ICP(name="rep", area="portland, or", categories=["dentist"],
                  service="reputation_management", prefer_established=False)
        store.save_icp("rep", icp.to_dict())
        store.add_review_signal("n1", "google", 2.4, 60)
        biz = apply_signal_update(store, icp, "n1")
        assert "weak_reviews" in biz["gap_flags"]
        assert biz["score"] > 90  # weight 1.0 for reputation service
        assert biz["confidence"] == "verified"

    def test_review_gaps_survive_and_merge_with_site_gaps(self, store):
        store.upsert_business(BIZ)
        icp = ICP(name="g", area="portland, or", categories=["dentist"],
                  service="general")
        store.save_icp("g", icp.to_dict())
        store.add_review_signal("n1", "google", 2.0, 40)
        # site check writes broken_site; review gap must merge, not vanish
        from leadshoot.pipeline import _persist_check
        row = store.conn.execute("SELECT * FROM businesses WHERE id='n1'").fetchone()
        _persist_check(store, row, CheckResult(status=BROKEN, http_code=500), icp)
        store.conn.commit()
        biz = store.get_business("n1")
        flags = biz["gap_flags"].split(",")
        assert "broken_site" in flags and "weak_reviews" in flags

    def test_leads_include_review_summary(self, store):
        store.upsert_business(BIZ)
        store.save_check("n1", "broken", 500, None, None, None,
                         ["broken_site"], "verified", 95)
        store.add_review_signal("n1", "google", 4.2, 80)
        lead = store.leads()[0]
        assert lead["reviews_rating"] == 4.2
        assert lead["reviews_count"] == 80
        assert lead["reviews_sources"] == "google"

    def test_search_claims_location_no_duplication(self, store):
        s1 = store.start_run("icp", "muscat")
        store.upsert_business(BIZ, search_id=s1)
        s2 = store.start_run("icp", "muscat")
        store.upsert_business(BIZ, search_id=s2)   # rediscovered
        store.conn.commit()
        n = store.conn.execute("SELECT COUNT(*) n FROM businesses").fetchone()["n"]
        assert n == 1                               # never duplicated
        store.save_check("n1", "broken", 500, None, None, None,
                         ["broken_site"], "verified", 95)
        assert store.leads(search_id=s2)            # new search owns it
        assert store.leads(search_id=s1) == []      # old search lost it

    def test_upsert_without_search_keeps_claim(self, store):
        s1 = store.start_run("icp", "muscat")
        store.upsert_business(BIZ, search_id=s1)
        store.upsert_business(BIZ)                  # e.g. legacy path
        store.conn.commit()
        row = store.conn.execute(
            "SELECT search_id FROM businesses WHERE id='n1'").fetchone()
        assert row["search_id"] == s1

    def test_run_history(self, store):
        a = store.start_run("icp", "muscat")
        b = store.start_run("icp", "salalah")
        store.finish_run(b, found=10, checked=8)
        assert store.latest_run_id() == b
        runs = store.list_runs()
        assert [r["id"] for r in runs] == [b, a]
        assert runs[0]["found"] == 10

    def test_migration_adds_search_id(self, tmp_path):
        path = tmp_path / "old.db"
        old = Store(path)                           # current schema…
        old.conn.execute("DROP INDEX IF EXISTS idx_biz_search")
        old.conn.execute("ALTER TABLE businesses DROP COLUMN search_id")
        old.conn.commit()
        old.close()                                 # …minus search_id = pre-migration DB
        st = Store(path)                            # must migrate, not raise
        cols = {r[1] for r in st.conn.execute("PRAGMA table_info(businesses)")}
        assert "search_id" in cols
        st.upsert_business(BIZ, search_id=7)        # and be usable
        st.conn.commit()
        st.close()

    def test_get_business_detail(self, store):
        store.upsert_business(BIZ)
        store.add_review_signal("n1", "yelp", 3.0, 25, url="https://yelp.example")
        biz = store.get_business("n1")
        assert biz["signals"][0]["source"] == "yelp"
        assert biz["reviews_rating"] == 3.0
        assert store.get_business("missing") is None


# ---------- generic signals: social, maturity, migration ----------

class TestSignals:
    WANTED = ["inactive_social", "weak_social", "broken_site"]

    def test_social_gaps(self):
        assert social_gaps(None, None, self.WANTED) == []       # unknown ≠ gap
        assert social_gaps(12000, 5, self.WANTED) == []          # healthy
        assert social_gaps(200, 5, self.WANTED) == ["weak_social"]
        assert social_gaps(12000, 200, self.WANTED) == ["inactive_social"]
        assert set(social_gaps(200, 200, self.WANTED)) == {
            "inactive_social", "weak_social"}

    def test_maturity_ladder(self):
        import datetime
        year = datetime.date.today().year
        est, f_est = maturity(year - 10)
        grow, f_grow = maturity(year - 2)
        new, f_new = maturity(year)
        unk, f_unk = maturity(None)
        assert (est, grow, new, unk) == ("established", "growing",
                                         "just_started", "unknown")
        # users avoid just-started; unknown is kept but below proven
        assert f_est > f_unk > f_new
        assert f_grow > f_unk

    def test_maturity_off(self):
        assert maturity(None, prefer_established=False)[1] == 1.0
        import datetime
        assert maturity(datetime.date.today().year,
                        prefer_established=False)[1] == 1.0

    def test_established_outranks_unknown_and_new(self, store):
        import datetime
        year = datetime.date.today().year
        for i, founded in [(1, year - 10), (2, None), (3, year)]:
            store.upsert_business({**BIZ, "id": f"n{i}",
                                   "name": f"Biz {i}"})
            store.save_check(f"n{i}", "broken", 500, None, None, None,
                             ["broken_site"], "verified", 0)
            if founded:
                store.add_signal(f"n{i}", "business.founded_year", "website",
                                 value=founded)
        icp = ICP(name="w", area="portland, or", categories=["dentist"])
        store.save_icp("w", icp.to_dict())
        scores = {}
        for i in (1, 2, 3):
            scores[i] = apply_signal_update(store, icp, f"n{i}")["score"]
        assert scores[1] > scores[2] > scores[3]   # est > unknown > new

    def test_generic_signal_summary(self, store):
        store.upsert_business(BIZ)
        store.add_signal("n1", "social.followers", "instagram", value=800)
        store.add_signal("n1", "social.followers", "facebook", value=400)
        store.add_signal("n1", "social.last_post_days", "instagram", value=120)
        store.add_signal("n1", "social.last_post_days", "facebook", value=30)
        store.add_signal("n1", "business.founded_year", "registry", value=2009)
        s = store.signal_summary("n1")
        assert s["social_followers"] == 1200          # total audience
        assert s["social_last_post_days"] == 30       # most recent activity
        assert s["founded_year"] == 2009

    def test_unknown_keys_stored_not_scored(self, store):
        store.upsert_business(BIZ)
        assert store.add_signal("n1", "custom.whatever", "somewhere",
                                value=42) is True
        icp = ICP(name="w", area="x", categories=["dentist"],
                  prefer_established=False)
        store.save_icp("w", icp.to_dict())
        biz = apply_signal_update(store, icp, "n1")
        assert biz["gap_flags"] == ""                 # stored, no effect
        assert any(x["key"] == "custom.whatever" for x in biz["signals"])

    def test_social_media_icp_scores_inactive(self, store):
        store.upsert_business(BIZ)
        store.save_check("n1", "working", 200, 1, 1, 1, [], "", 0)
        icp = ICP(name="smm", area="portland, or", categories=["dentist"],
                  service="social_media", prefer_established=False)
        store.save_icp("smm", icp.to_dict())
        store.add_signal("n1", "social.last_post_days", "instagram", value=180)
        biz = apply_signal_update(store, icp, "n1")
        assert "inactive_social" in biz["gap_flags"]
        assert biz["score"] >= 100 - 1

    def test_candidate_gaps_headline_axis(self):
        social = {"inactive_social": 1.0, "weak_social": 0.8}
        reviews = {"weak_reviews": 1.0, "few_reviews": 0.8}
        website = {"no_website": 0.9, "broken_site": 1.0}
        blank = {"reviews_count": None, "reviews_rating": None,
                 "social_followers": None, "social_last_post_days": None}
        # the offer's headline axis decides which placeholder (if any) shows
        assert candidate_gaps(social, blank) == ["social_unchecked"]
        assert candidate_gaps(reviews, blank) == ["reviews_unchecked"]
        assert candidate_gaps(website, blank) == []       # site offer: none
        # a recorded signal on that axis retires the placeholder
        assert candidate_gaps(social, {**blank, "social_followers": 800}) == []
        assert candidate_gaps(reviews, {**blank, "reviews_count": 12}) == []

    def test_social_media_surfaces_candidate_not_website(self, store):
        # a social-media seller must see the lead framed by THEIR offer, not
        # "no website", even before any social research is done.
        store.upsert_business(BIZ)
        store.save_check("n1", NO_SITE, None, None, None, None, [], "", 0)
        icp = ICP(name="smm", area="portland, or", categories=["dentist"],
                  service="social_media")
        store.save_icp("smm", icp.to_dict())
        biz = apply_signal_update(store, icp, "n1")
        assert "social_unchecked" in biz["gap_flags"]
        assert "no_website" not in biz["gap_flags"]        # offer-framed
        assert biz["confidence"] == UNVERIFIED             # a research cue
        assert biz["score"] >= icp.min_score               # surfaces, not cut
        # researching the signal replaces the placeholder with the real gap
        store.add_signal("n1", "social.last_post_days", "instagram", value=180)
        biz = apply_signal_update(store, icp, "n1")
        assert "inactive_social" in biz["gap_flags"]
        assert "social_unchecked" not in biz["gap_flags"]
        assert biz["confidence"] == VERIFIED

    def test_researched_official_site_retires_false_no_website(self, store):
        store.upsert_business({**BIZ, "osm_website": None})
        store.save_check("n1", NO_SITE, None, None, None, None,
                         ["no_website"], UNVERIFIED, 50)
        icp = ICP(name="web", area="portland, or", categories=["dentist"])
        store.save_icp("web", icp.to_dict())
        assert store.add_signal(
            "n1", "website.official_url", "web_search",
            text="https://real.example", url="https://real.example",
        )
        biz = apply_signal_update(store, icp, "n1")
        assert biz["osm_website"] == "https://real.example"
        assert biz["official_website"] == "https://real.example"
        assert "no_website" not in biz["gap_flags"]
        # A new provider roster with the site still missing must not clobber
        # the sourced correction.
        store.upsert_business({**BIZ, "osm_website": None}, search_id=2)
        store.conn.commit()
        assert store.get_business("n1")["osm_website"] == \
            "https://real.example"

    def test_migration_preserves_review_data(self, tmp_path):
        import sqlite3 as s3
        path = tmp_path / "v01.db"
        first = Store(path)
        first.upsert_business(BIZ)
        first.conn.commit()
        first.close()
        conn = s3.connect(path)                       # simulate v0.1 schema
        conn.execute("DROP TABLE signals")
        conn.execute("""CREATE TABLE review_signals (
            business_id TEXT NOT NULL, source TEXT NOT NULL, rating REAL,
            review_count INTEGER, url TEXT, note TEXT DEFAULT '',
            added_at TEXT, PRIMARY KEY (business_id, source))""")
        conn.execute("INSERT INTO review_signals VALUES "
                     "('n1','google',4.5,120,'https://g.example','','2026-01-01')")
        conn.commit(); conn.close()
        st = Store(path)                              # migrates
        s = st.signal_summary("n1")
        assert s["reviews_rating"] == 4.5 and s["reviews_count"] == 120
        legacy = st.conn.execute("SELECT name FROM sqlite_master WHERE "
                                 "name='review_signals'").fetchone()
        assert legacy is None
        st.close()

    def test_custom_gaps_get_weights(self):
        icp = ICP(name="x", area="a", categories=["cafe"],
                  service="website_design",
                  gaps=["broken_site", "inactive_social"])
        assert icp.weights["inactive_social"] > 0     # setdefault filled it
