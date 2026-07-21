"""REST filter contract: /api/options vocabulary + /api/leads filtering.

The web UI builds its filter controls from /api/options - the same
vocabulary as `leadshoot options` and MCP list_options - so these tests pin
the agent-facing determinism: every gap the engine can compute is exposed,
and every filter narrows exactly.
"""

import pytest
from fastapi.testclient import TestClient

from leadshoot.api import create_app
from leadshoot.icp import GAP_WEIGHTS
from leadshoot.store import STAGES, Store


@pytest.fixture
def client(tmp_path):
    db = str(tmp_path / "api.db")
    s = Store(db)
    run = s.start_run("demo", "Testville")
    for i, gap in enumerate(sorted(GAP_WEIGHTS)):
        biz_id = f"n{i}"
        s.upsert_business(dict(
            id=biz_id, name=f"{gap} co", category="cafe", osm_tags="{}",
            phone=None, email=None, address=None, lat=1.0, lon=2.0,
            osm_website=None if gap == "no_website" else f"http://{i}.example",
            area="Testville"), search_id=run)
        s.save_check(biz_id, site_status="working", http_code=200,
                     has_ssl=1, is_mobile=1, has_booking=1,
                     gap_flags=[gap], confidence="verified", score=90 - i * 5)
    s.mark("n0", stage="contacted")
    s.finish_run(run, found=len(GAP_WEIGHTS), checked=len(GAP_WEIGHTS))
    s.conn.commit()
    s.close()
    return TestClient(create_app(db))


class TestOptions:
    def test_exposes_full_engine_vocabulary(self, client):
        o = client.get("/api/options").json()
        assert o["gaps"] == sorted(GAP_WEIGHTS)   # every computable gap
        assert o["stages"] == list(STAGES)
        assert o["categories"] and o["services"]

    def test_signal_gaps_included(self, client):
        gaps = client.get("/api/options").json()["gaps"]
        for g in ("weak_reviews", "few_reviews", "inactive_social",
                  "weak_social"):
            assert g in gaps


class TestLeadsFilters:
    def test_no_filter_returns_all(self, client):
        assert client.get("/api/leads").json()["count"] == len(GAP_WEIGHTS)

    @pytest.mark.parametrize("gap", sorted(GAP_WEIGHTS))
    def test_every_gap_filters_to_exactly_its_lead(self, client, gap):
        leads = client.get(f"/api/leads?gap={gap}").json()["leads"]
        assert len(leads) == 1
        assert leads[0]["name"] == f"{gap} co"

    def test_stage_filter(self, client):
        leads = client.get("/api/leads?stage=contacted").json()["leads"]
        assert [l["id"] for l in leads] == ["n0"]

    def test_min_score_filter(self, client):
        leads = client.get("/api/leads?min_score=80").json()["leads"]
        assert {l["score"] >= 80 for l in leads} == {True}
        assert len(leads) == 3  # 90, 85, 80

    def test_search_scope_filter(self, client):
        assert client.get("/api/leads?search_id=999").json()["count"] == 0


class TestFacets:
    """Dynamic filters: /api/facets offers only what the data contains."""

    def test_facets_list_only_present_gaps(self, client):
        f = client.get("/api/facets").json()
        # the fixture seeds exactly one business per gap
        assert set(f["gaps"]) == set(sorted(GAP_WEIGHTS))
        assert all(c == 1 for c in f["gaps"].values())

    def test_facets_scoped_to_search(self, client):
        # everything in the fixture is one search; an unknown scope is empty
        assert client.get("/api/facets?search_id=999").json()["gaps"] == {}

    def test_facets_stage_counts(self, client):
        f = client.get("/api/facets").json()
        assert f["stages"] == {"contacted": 1}

    def test_facets_reflect_a_narrower_reality(self, tmp_path):
        """A search with only broken sites offers only broken_site - never
        the full vocabulary."""
        db = str(tmp_path / "narrow.db")
        s = Store(db)
        run = s.start_run("d", "Town")
        for i in range(3):
            s.upsert_business(dict(
                id=f"b{i}", name=f"b{i}", category="cafe", osm_tags="{}",
                phone=None, email=None, address=None, lat=1.0, lon=2.0,
                osm_website="http://x.example", area="Town"), search_id=run)
            s.save_check(f"b{i}", site_status="broken", http_code=404,
                         has_ssl=1, is_mobile=1, has_booking=1,
                         gap_flags=["broken_site"], confidence="verified",
                         score=80)
        s.conn.commit()
        s.close()
        f = TestClient(create_app(db)).get("/api/facets").json()
        assert f["gaps"] == {"broken_site": 3}
