"""Niche identifier determinism + fit-mode scoring. No network."""

import pytest

from leadshoot.check import CheckResult
from leadshoot.icp import ICP
from leadshoot.niche import identify
from leadshoot.pipeline import _persist_check, apply_signal_update
from leadshoot.score import fit_score
from leadshoot.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "niche.db")
    yield s
    s.close()


BIZ = {
    "id": "n1", "name": "Village Cafe", "category": "cafe",
    "osm_tags": "amenity=cafe", "phone": "+1-212-555-0100", "email": None,
    "address": "1 Main St", "lat": 40.7, "lon": -74.0,
    "osm_website": "https://village.example", "area": "gv",
}


class TestNicheIdentifier:
    def test_deterministic(self):
        a = identify("I roast specialty coffee beans").to_dict()
        b = identify("I roast specialty coffee beans").to_dict()
        assert a == b

    def test_user_examples_all_map(self):
        # the exact niches the product owner named: social media, coffee,
        # software, designs - plus the classic websites
        assert identify("we build websites").mode == "gaps"
        assert identify("I manage social media for businesses").service == "social_media"
        coffee = identify("I sell a special type of coffee")
        assert coffee.mode == "fit"
        assert "cafe" in coffee.categories
        assert identify("we sell software").mode == "clarify"
        design = identify("I sell logo designs")
        assert design.mode == "gaps" and "diy_builder" in design.gaps

    def test_physical_product_is_fit(self):
        plan = identify("wholesale produce distributor")
        assert plan.mode == "fit"
        assert plan.gaps == {}
        assert "restaurant" in plan.categories
        assert plan.ask  # area still needs asking

    def test_gaps_plans_carry_weights_and_questions(self):
        plan = identify("website design for small businesses")
        assert plan.gaps["broken_site"] == 1.0
        assert any("Where do you work" in q for q in plan.ask)

    def test_unknown_asks_instead_of_guessing(self):
        plan = identify("quantum synergy consulting")
        assert plan.mode == "clarify"
        assert len(plan.ask) >= 2
        assert plan.matched_rule == "none"

    def test_first_match_wins_is_stable(self):
        # 'website booking portal' hits the websites rule first, always
        assert identify("website booking portal").matched_rule == "websites"


class TestFitMode:
    def test_fit_icp_clears_gaps(self):
        icp = ICP(name="c", area="gv", categories=["cafe"], mode="fit")
        assert icp.gaps == []
        assert icp.to_dict()["mode"] == "fit"

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError, match="mode"):
            ICP(name="c", area="gv", categories=["cafe"], mode="vibes")

    def test_healthy_buyer_outranks_struggling(self):
        healthy = fit_score("working", 4.8, 200, 8000, 5, True, 1.08)
        quiet = fit_score("working", None, None, None, None, True, 0.85)
        struggling = fit_score("broken", 2.4, 40, None, 400, False, 0.85)
        assert healthy == 100
        assert healthy > quiet > struggling

    def test_fit_persist_scores_without_gaps(self, store):
        store.upsert_business(BIZ)
        icp = ICP(name="coffee", area="gv", categories=["cafe"], mode="fit")
        store.save_icp("coffee", icp.to_dict())
        row = store.conn.execute(
            "SELECT * FROM businesses WHERE id='n1'").fetchone()
        _persist_check(store, row,
                       CheckResult(status="working", http_code=200,
                                   is_mobile=1, has_booking=0), icp)
        store.conn.commit()
        biz = store.get_business("n1")
        assert biz["gap_flags"] == ""      # nothing flagged in fit mode
        assert biz["score"] > 0            # yet it ranks

    def test_fit_signal_update_raises_score_for_good_reviews(self, store):
        store.upsert_business(BIZ)
        store.save_check("n1", "working", 200, 1, 1, 1, [], "", 0)
        icp = ICP(name="coffee", area="gv", categories=["cafe"], mode="fit",
                  prefer_established=False)
        store.save_icp("coffee", icp.to_dict())
        base = apply_signal_update(store, icp, "n1")["score"]
        store.add_review_signal("n1", "google", 4.8, 150)
        boosted = apply_signal_update(store, icp, "n1")["score"]
        assert boosted > base

    def test_new_search_rescores_fresh_checks_under_its_own_icp(self, store,
                                                                monkeypatch):
        """Regression: scores are ICP-relative. A business live-checked
        minutes ago under a website ICP must be RESCORED (from stored
        facts, no refetch) when a fit-mode search claims it."""
        import leadshoot.pipeline as pl

        store.upsert_business(BIZ)
        store.save_check("n1", "broken", 500, None, None, None,
                         ["broken_site"], "verified", 89)  # fresh gap score
        original_checked_at = store.conn.execute(
            "SELECT checked_at FROM businesses WHERE id='n1'"
        ).fetchone()["checked_at"]

        monkeypatch.setattr(pl, "ingest", lambda store, *a, **k: (
            store.upsert_business(BIZ, search_id=k.get("search_id")) or 1))
        monkeypatch.setattr(pl, "run_checks",
                            lambda urls, **k: (_ for _ in ()).throw(
                                AssertionError("must not refetch fresh rows"))
                            if urls else {})

        icp = ICP(name="coffee", area="gv", categories=["cafe"], mode="fit",
                  min_score=1)
        store.save_icp("coffee", icp.to_dict())
        leads = pl.find_leads(store, icp, limit=5)

        assert leads and leads[0]["id"] == "n1"
        assert leads[0]["gap_flags"] == ""          # fit: nothing flagged
        assert leads[0]["score"] > 0                # yet ranked
        assert leads[0]["checked_at"] == original_checked_at  # honest staleness

    def test_same_business_opposite_polarity(self, store):
        """The core niche-agnostic property: one thriving cafe is a ZERO for
        a website seller and a TOP lead for a coffee supplier."""
        store.upsert_business(BIZ)
        store.add_review_signal("n1", "google", 4.9, 300)
        row = store.conn.execute(
            "SELECT * FROM businesses WHERE id='n1'").fetchone()
        result = CheckResult(status="working", http_code=200, is_mobile=1,
                             has_booking=1)
        web = ICP(name="w", area="gv", categories=["cafe"],
                  service="website_design")
        store.save_icp("w", web.to_dict())
        _persist_check(store, row, result, web)
        store.conn.commit()
        web_score = store.get_business("n1")["score"]

        fit = ICP(name="f", area="gv", categories=["cafe"], mode="fit")
        store.save_icp("f", fit.to_dict())
        _persist_check(store, row, result, fit)
        store.conn.commit()
        fit_lead_score = store.get_business("n1")["score"]

        assert web_score == 0          # nothing to fix -> not a web lead
        assert fit_lead_score >= 75    # thriving -> prime buyer (age unknown
                                       # still discounts ×0.85, as designed)
        store.add_signal("n1", "business.founded_year", "website", value=2008)
        _persist_check(store, row, result, fit)
        store.conn.commit()
        assert store.get_business("n1")["score"] > fit_lead_score  # est. boost
