"""The reactive session feed: change_token + per-result streaming hooks."""

import pytest

from leadshoot.check import CheckResult, run_checks
from leadshoot.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "reactive.db")
    yield s
    s.close()


BIZ = dict(id="n1", name="Cafe One", category="cafe", osm_tags="{}",
           phone=None, email=None, address="1 Main St", lat=1.0, lon=2.0,
           osm_website="http://one.example", area="Testville")


class TestChangeToken:
    def test_stable_when_nothing_changes(self, store):
        assert store.change_token() == store.change_token()

    def test_changes_on_roster_upsert(self, store):
        before = store.change_token()
        store.upsert_business(dict(BIZ))
        store.conn.commit()
        assert store.change_token() != before

    def test_changes_on_check_persisted(self, store):
        store.upsert_business(dict(BIZ))
        store.conn.commit()
        before = store.change_token()
        store.save_check("n1", site_status="broken", http_code=404,
                         has_ssl=None, is_mobile=None, has_booking=None,
                         gap_flags=["broken_site"], confidence="verified",
                         score=80)
        store.conn.commit()
        assert store.change_token() != before

    def test_changes_on_run_lifecycle(self, store):
        before = store.change_token()
        run_id = store.start_run("icp", "Testville")
        mid = store.change_token()
        assert mid != before
        store.finish_run(run_id, found=1, checked=1)
        assert store.change_token() != mid

    def test_changes_on_stage_mark(self, store):
        store.upsert_business(dict(BIZ))
        store.conn.commit()
        before = store.change_token()
        assert store.mark("n1", stage="contacted")
        assert store.change_token() != before

    def test_changes_on_signal(self, store):
        store.upsert_business(dict(BIZ))
        store.conn.commit()
        before = store.change_token()
        store.add_signal("n1", "reviews.rating", "google", value=4.5)
        store.conn.commit()
        assert store.change_token() != before

    def test_visible_across_connections(self, store, tmp_path):
        """A watcher on its own connection must see the writer's commits -
        the whole reactive UI rests on this."""
        watcher = Store(tmp_path / "reactive.db")
        before = watcher.change_token()
        store.upsert_business(dict(BIZ))
        store.conn.commit()
        assert watcher.change_token() != before
        watcher.close()


class TestOnResultStreaming:
    def test_on_result_fires_per_site(self, monkeypatch):
        async def fake_check_url(client, url, robots_cache, _root_retry=True):
            return CheckResult(status="working", http_code=200)

        monkeypatch.setattr("leadshoot.check.check_url", fake_check_url)
        seen = []
        results = run_checks({"a": "http://a.example", "b": "http://b.example"},
                             on_result=lambda biz_id, r: seen.append((biz_id, r)))
        assert sorted(dict(seen)) == ["a", "b"]
        assert set(results) == {"a", "b"}
        for _, r in seen:
            assert r.status == "working"

    def test_no_callback_still_works(self, monkeypatch):
        async def fake_check_url(client, url, robots_cache, _root_retry=True):
            return CheckResult(status="working")

        monkeypatch.setattr("leadshoot.check.check_url", fake_check_url)
        assert run_checks({"a": "http://a.example"})["a"].status == "working"


class TestStreamRoute:
    def test_stream_route_registered(self, tmp_path):
        from leadshoot.api import create_app

        app = create_app(str(tmp_path / "api.db"))
        assert any(getattr(r, "path", "") == "/api/stream" for r in app.routes)
