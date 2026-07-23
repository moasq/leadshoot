"""MCP server - the agent face of LeadShoot.

Agents hold no state. Call `status` first each session: it reports which ICPs
exist and where the pipeline stands, so any agent (Claude, Cursor, anything)
can resume exactly where another left off.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from . import OSM_ATTRIBUTION
from .export import to_csv, to_json
from .icp import CATEGORIES, GAP_WEIGHTS, ICP, SERVICES, infer_gaps
from .pipeline import apply_signal_update, enrich_domain_age
from .pipeline import find_leads as run_find
from .pipeline import import_gmaps as run_import_gmaps
from .pipeline import recheck as run_recheck
from .store import KNOWN_SIGNAL_KEYS, STAGES, Store


def build_server(db: str | None = None, host: str = "127.0.0.1",
                 port: int = 8322) -> FastMCP:
    mcp = FastMCP(
        "leadshoot",
        host=host,
        port=port,
        instructions=(
            "LeadShoot finds local businesses missing whatever the user sells "
            "- the user's service defines the gaps that count: websites "
            "(no/broken/insecure site), redesigns (outdated tech, DIY "
            "builders, slow), social media (dormant accounts), booking "
            "software (no online booking), reputation (weak reviews), or a "
            "custom gap set. Verified live on open data, ranked by "
            "opportunity. Call status first. If no ICP exists, elicit one: "
            "what service they sell (this infers the gaps), where they "
            "work, which business categories, whether to exclude chains - "
            "then save_icp. Businesses only, no email harvesting. "
            + OSM_ATTRIBUTION
        ),
    )

    def _store() -> Store:
        return Store(db)

    def _icp(store: Store, name: str | None) -> ICP:
        if name is None:
            icps = store.list_icps()
            if len(icps) != 1:
                raise ValueError(
                    "Specify icp_name. Existing: "
                    + json.dumps([i["name"] for i in icps])
                )
            name = icps[0]["name"]
        definition = store.get_icp(name)
        if definition is None:
            raise ValueError(f"ICP not found: {name}")
        return ICP.from_dict(definition)

    @mcp.tool()
    def status() -> dict:
        """Engine state: ICPs, pipeline counts, last run. Call this first
        every session - it tells you whether this is a fresh install (no
        ICPs -> elicit one) or a resume (pick up the existing pipeline)."""
        return _store().status()

    @mcp.tool()
    def list_options() -> dict:
        """Valid categories, services (each implies gap weights), and stages -
        use these when eliciting or validating an ICP."""
        return {
            "categories": sorted(CATEGORIES),
            "services": {s: infer_gaps(s) for s in SERVICES},
            "stages": list(STAGES),
        }

    @mcp.tool()
    def identify_niche(description: str) -> dict:
        """FIRST STEP of ICP creation: deterministically map the user's own
        words for what they sell into a targeting plan. Returns mode
        ('gaps' = find businesses with fixable problems; 'fit' = find
        healthy BUYERS for a product/supply niche where good reviews and
        maturity rank UP; 'clarify' = ask the returned questions and re-run),
        plus suggested buyer categories, the explanation to give the user
        ('say'), and what still needs asking ('ask'). Same input always
        returns the same plan - use it instead of guessing, then save_icp
        with its mode/service/categories once the user confirms."""
        from .niche import identify

        return identify(description).to_dict()

    @mcp.tool()
    def save_icp(
        name: str,
        area: str,
        categories: list[str],
        service: str = "website_design",
        exclude_chains: bool = True,
        min_score: int = 30,
        gaps: list[str] | None = None,
        prefer_established: bool = True,
        provider: str = "osm",
        mode: str = "gaps",
    ) -> dict:
        """Create or update an ICP (ideal customer profile). `service` infers
        which gaps to target and their weights. Pass `gaps` to customize
        targeting - ONLY after the user explicitly confirmed targeting
        outside their niche. prefer_established ranks 3y+ businesses above
        just-started and unknown-age ones (most users avoid new-business
        risk). provider: 'osm' (default, open data), 'overture' (big open
        data), or 'gmaps' (opt-in - the user's own gosom scraper; against
        Google ToS, requires the user's explicit informed choice). mode:
        'gaps' (default) or 'fit' for product/supply niches where healthy
        buyers rank up and nothing is flagged - identify_niche suggests it.
        Returns the saved ICP."""
        icp = ICP(name=name, area=area, categories=categories,
                  service=service, gaps=list(gaps or []),
                  exclude_chains=exclude_chains, min_score=min_score,
                  prefer_established=prefer_established, provider=provider,
                  mode=mode)
        store = _store()
        store.save_icp(icp.name, icp.to_dict())
        return icp.to_dict()

    @mcp.tool()
    def list_icps() -> list[dict]:
        """All saved ICPs."""
        return _store().list_icps()

    @mcp.tool()
    def find_leads(icp_name: str | None = None, limit: int = 25,
                   open_ui: bool = True) -> dict:
        """Find fresh leads for an ICP: pulls the OSM roster, live-checks
        every website, scores the gaps, and returns ranked leads. Excludes
        anything the user already contacted/won/hidden. May take a minute
        for large areas.

        By default this also opens the live map in the user's browser so
        they watch pins land while the search runs (open_ui=False or
        LEADSHOOT_NO_OPEN=1 to skip - e.g. on a headless host)."""
        store = _store()
        icp = _icp(store, icp_name)
        map_url = None
        if open_ui:
            from .ui import ensure_ui

            map_url = ensure_ui(db)   # best-effort, never raises
        leads = run_find(store, icp, limit=limit)
        return {"attribution": OSM_ATTRIBUTION, "count": len(leads),
                "search_id": store.latest_run_id(), "live_map": map_url,
                "leads": leads}

    @mcp.tool()
    def list_leads(
        stage: str | None = None,
        gap: str | None = None,
        min_score: int = 0,
        limit: int = 50,
        search_id: int | None = None,
    ) -> list[dict]:
        """Leads already in the database (the user's working pipeline).
        Filter by stage (new/contacted/interested/won/lost/hidden), gap flag
        (broken_site/no_website/no_ssl/not_mobile/no_booking/weak_reviews/
        few_reviews), score, or search_id (scope to one search version -
        each find is a numbered search that owns exactly what it found)."""
        return _store().leads(stage=stage, gap=gap, min_score=min_score,
                              limit=limit, search_id=search_id)

    @mcp.tool()
    def list_searches(limit: int = 20) -> list[dict]:
        """Search history, newest first. Every find_leads call is a numbered
        search (its version). A business rediscovered by a newer search is
        claimed by it - locations are never duplicated across searches."""
        return _store().list_runs(limit=limit)

    @mcp.tool()
    def update_lead(business_id: str, stage: str | None = None,
                    note: str | None = None) -> dict:
        """Update the user's pipeline for one lead: stage and/or note.
        Facts (site status, score) are engine-owned and can't be set here."""
        ok = _store().mark(business_id, stage=stage, note=note)
        if not ok:
            raise ValueError(f"No business with id {business_id}")
        return {"business_id": business_id, "stage": stage, "note": note}

    @mcp.tool()
    def import_gmaps_results(file_path: str, icp_name: str | None = None,
                             fallback_category: str | None = None,
                             limit: int = 25) -> dict:
        """Import a gosom/google-maps-scraper results file (JSON or CSV) the
        USER produced themselves, as a versioned search: LeadShoot live-checks
        every listed website, auto-records Google review aggregates as
        signals, scores gaps, and returns ranked leads. Only offer this when
        the user explicitly wants Google Maps data - scraping it violates
        Google's ToS and is their informed choice. Harvested emails in the
        file are refused."""
        store = _store()
        icp = _icp(store, icp_name)
        leads = run_import_gmaps(store, icp, file_path, limit=limit,
                                 fallback_category=fallback_category)
        return {"count": len(leads), "leads": leads}

    @mcp.tool()
    def get_lead(business_id: str) -> dict:
        """Full detail for one lead: facts, gap flags, recorded review
        signals, and the user's stage/note."""
        biz = _store().get_business(business_id)
        if biz is None:
            raise ValueError(f"No business with id {business_id}")
        return biz

    @mcp.tool()
    def add_signal(
        business_id: str,
        key: str,
        source: str,
        value: float | None = None,
        text: str | None = None,
        url: str | None = None,
        note: str = "",
        icp_name: str | None = None,
    ) -> dict:
        """Record ONE researched signal about a business and rescore the
        lead. Scored keys: reviews.rating (0-5), reviews.count,
        social.followers, social.last_post_days, business.founded_year.
        Any other key is stored but not scored (extensible). Sources:
        google, yelp, instagram, facebook, website, registry, linkedin, ….
        Aggregates and public business facts ONLY - never review text,
        reviewer identities, or personal data. Unknown is never a gap;
        unknown founding age ranks below established. Returns the rescored
        lead."""
        store = _store()
        if not store.add_signal(business_id, key, source, value=value,
                                text=text, url=url, note=note):
            raise ValueError(f"No business with id {business_id}")
        icp = _icp(store, icp_name)
        return apply_signal_update(store, icp, business_id)

    @mcp.tool()
    def add_review_signal(
        business_id: str,
        source: str,
        rating: float | None = None,
        review_count: int | None = None,
        url: str | None = None,
        note: str = "",
        icp_name: str | None = None,
    ) -> dict:
        """Convenience wrapper over add_signal for review aggregates:
        records reviews.rating and/or reviews.count from one source and
        rescores. Same rules: aggregates only, never review text or
        reviewer identities."""
        store = _store()
        if not store.add_review_signal(business_id, source, rating=rating,
                                       review_count=review_count, url=url,
                                       note=note):
            raise ValueError(f"No business with id {business_id}")
        icp = _icp(store, icp_name)
        return apply_signal_update(store, icp, business_id)

    @mcp.tool()
    def enrich_leads(icp_name: str | None = None, limit: int = 50) -> dict:
        """Automatically date leads via RDAP domain-registration lookups
        (open protocol, no keys, polite). Domain age is a lower bound for
        business age - after this, 'age unknown' leads rank fairly under the
        maturity qualifier. Run it after a find when many leads show no
        founded year."""
        store = _store()
        icp = _icp(store, icp_name)
        return {"enriched": enrich_domain_age(store, icp, limit=limit)}

    @mcp.tool()
    def recheck(icp_name: str | None = None, stage: str | None = None) -> dict:
        """Re-run live checks (did they fix their site?). Refreshes facts
        only; the user's stages and notes are untouched."""
        store = _store()
        icp = _icp(store, icp_name)
        n = run_recheck(store, icp, stage=stage)
        return {"rechecked": n}

    @mcp.tool()
    def export_leads(format: str = "csv", stage: str | None = None,
                     min_score: int = 0) -> str:
        """Export leads (with stages/notes) as CSV or JSON text for the
        user's CRM. Output includes the required OSM attribution."""
        rows = _store().leads(stage=stage, min_score=min_score, limit=100_000)
        return to_csv(rows) if format == "csv" else to_json(rows)

    return mcp


if __name__ == "__main__":
    build_server().run()
