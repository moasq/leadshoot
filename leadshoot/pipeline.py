"""Pipeline orchestration: ICP -> roster -> dedup -> live check -> score."""

from __future__ import annotations

from .check import CheckResult, run_checks
from .icp import ICP, SIGNAL_GAPS, selectors_for
from .ingest import ingest
from .score import (NO_SITE, UNVERIFIED, VERIFIED, fit_score, gaps_from_check,
                    maturity, review_gaps, score, social_gaps)
from .store import K_BUILDER, K_DOMAIN_YEAR, Store


def _signal_gaps_and_factor(store: Store, biz_id: str,
                            icp: ICP) -> tuple[list[str], float]:
    """Gaps derived from recorded signals + the maturity score factor."""
    s = store.signal_summary(biz_id)
    gaps = review_gaps(s["reviews_rating"], s["reviews_count"], icp.gaps)
    gaps += social_gaps(s["social_followers"], s["social_last_post_days"],
                        icp.gaps)
    # domain registration year is a maturity floor when founding is unknown
    age_evidence = s["founded_year"] or s["domain_registered_year"]
    _, factor = maturity(age_evidence, icp.prefer_established)
    return gaps, factor


def _persist_check(store: Store, row, result: CheckResult, icp: ICP,
                   checked_at: str | None = None) -> None:
    """Compute site gaps from the check, merge signal-derived gaps, apply
    the maturity qualifier, score, save. The single write path.

    Fit-mode ICPs invert the polarity: nothing is flagged, and business
    health (site up, reviews, activity, maturity) ranks the buyer.
    checked_at: pass the row's original timestamp when rescoring from
    stored facts, so staleness tracking stays truthful."""
    biz_id = row["id"]
    has_tag = bool(row["osm_website"])
    if result.builder:
        store.add_signal(biz_id, K_BUILDER, "leadshoot", text=result.builder)

    if icp.mode == "fit":
        summary = store.signal_summary(biz_id)
        age = summary["founded_year"] or summary["domain_registered_year"]
        _, factor = maturity(age, icp.prefer_established)
        s = fit_score(result.status if has_tag else NO_SITE,
                      summary["reviews_rating"], summary["reviews_count"],
                      summary["social_followers"],
                      summary["social_last_post_days"],
                      has_phone=bool(row["phone"]), maturity_factor=factor)
        gaps: list[str] = []
        confidence = ""
    else:
        site_gaps, confidence = gaps_from_check(result, has_tag, icp.gaps)
        sig_gaps, factor = _signal_gaps_and_factor(store, biz_id, icp)
        gaps = site_gaps + [g for g in sig_gaps if g not in site_gaps]
        if not site_gaps and sig_gaps:
            confidence = VERIFIED  # signals carry their own recorded sources
        s = score(gaps, icp.weights, has_phone=bool(row["phone"]),
                  confidence=confidence, maturity_factor=factor)
    store.save_check(
        biz_id,
        site_status=result.status if has_tag else NO_SITE,
        http_code=result.http_code,
        has_ssl=1 if result.status == "working" else
                (0 if result.status == "no_ssl" else None),
        is_mobile=result.is_mobile,
        has_booking=result.has_booking,
        gap_flags=gaps,
        confidence=confidence if gaps else "",
        score=s,
        site_outdated=result.outdated,
        site_slow=result.slow,
        checked_at=checked_at,
    )


def _result_from_row(store: Store, row) -> CheckResult:
    """Rebuild a CheckResult from stored facts so a business can be
    RESCORED under a different ICP without refetching. Scores are
    ICP-relative; fetch facts are not."""
    summary = store.signal_summary(row["id"])
    return CheckResult(
        status=row["site_status"] or NO_SITE,
        http_code=row["http_code"],
        is_mobile=row["is_mobile"],
        has_booking=row["has_booking"],
        builder=summary["builder"],
        outdated=row["site_outdated"] or 0,
        slow=row["site_slow"] or 0,
    )


def apply_signal_update(store: Store, icp: ICP, business_id: str) -> dict | None:
    """Rescore one business after its signals changed. Site facts and the
    user's pipeline are untouched."""
    biz = store.get_business(business_id)
    if biz is None:
        return None
    if icp.mode == "fit":
        age = biz["founded_year"] or biz["domain_registered_year"]
        _, factor = maturity(age, icp.prefer_established)
        s = fit_score(biz["site_status"], biz["reviews_rating"],
                      biz["reviews_count"], biz["social_followers"],
                      biz["social_last_post_days"],
                      has_phone=bool(biz["phone"]), maturity_factor=factor)
        store.update_gaps_score(business_id, [], "", s)
        return store.get_business(business_id)
    stored = [g for g in (biz["gap_flags"] or "").split(",") if g]
    site_gaps = [g for g in stored if g not in SIGNAL_GAPS]
    sig_gaps, factor = _signal_gaps_and_factor(store, business_id, icp)
    gaps = site_gaps + [g for g in sig_gaps if g not in site_gaps]
    confidence = biz["confidence"] if site_gaps else (VERIFIED if gaps else "")
    s = score(gaps, icp.weights, has_phone=bool(biz["phone"]),
              confidence=confidence or VERIFIED, maturity_factor=factor)
    store.update_gaps_score(business_id, gaps, confidence if gaps else "", s)
    return store.get_business(business_id)


# back-compat alias (pre-signals name)
apply_review_update = apply_signal_update


def find_leads(store: Store, icp: ICP, limit: int = 25,
               max_age_days: int = 30, progress=None) -> list[dict]:
    """The headline operation: one versioned search.

    Each call is a new search (the run id is its version). Businesses found
    are claimed by this search; results are scoped to exactly this search's
    roster - result sets never accumulate across searches.
    """
    run_id = store.start_run(icp.name, icp.area)

    if progress:
        progress(f"search #{run_id}: pulling roster for {icp.area} "
                 f"({icp.provider})")
    if icp.provider == "gmaps":
        from .gmaps import import_results, run_scrape

        results_file = run_scrape(store, icp.area, icp.categories,
                                  progress=progress)
        found = import_results(store, results_file, icp.area,
                               search_id=run_id)
    elif icp.provider == "overture":
        from .ingest import geocode_area
        from .overture import ingest_overture

        bbox = geocode_area(store, icp.area)
        found = ingest_overture(store, icp.area, icp.categories, bbox,
                                search_id=run_id, progress=progress)
    else:
        found = ingest(
            store, icp.area, icp.categories, selectors_for(icp.categories),
            exclude_chains=icp.exclude_chains, search_id=run_id,
            progress=progress,
        )

    stale = store.candidates_for_check(run_id, max_age_days=max_age_days)
    stale_ids = {r["id"] for r in stale}
    rows_by_id = {r["id"]: r for r in stale}
    with_site = {r["id"]: r["osm_website"] for r in stale if r["osm_website"]}
    without_site = [r for r in stale if not r["osm_website"]]

    if progress:
        progress(f"live-checking {len(with_site)} sites "
                 f"({len(without_site)} have no site listed)")

    # Each result commits as it lands, so watchers (map UI, other agents on
    # the same DB) see the search fill in live instead of all at once.
    persisted: set[str] = set()
    for row in without_site:  # no fetch needed - visible immediately
        _persist_check(store, row, CheckResult(status=NO_SITE), icp)
        persisted.add(row["id"])
    store.conn.commit()

    def _stream_persist(biz_id: str, result: CheckResult) -> None:
        _persist_check(store, rows_by_id[biz_id], result, icp)
        persisted.add(biz_id)
        store.conn.commit()

    results = run_checks(with_site, progress=progress,
                         on_result=_stream_persist)

    # every business in THIS search is (re)scored under THIS ICP: fresh
    # fetches for the stale, stored facts for the rest. Scores are
    # ICP-relative; a fit ICP must not inherit a gap ICP's numbers.
    checked = 0
    for row in store.businesses_in_search(run_id):
        if row["id"] in persisted:
            checked += 1
        elif row["id"] in stale_ids:
            result = results.get(row["id"], CheckResult(status=NO_SITE))
            _persist_check(store, row, result, icp)
            checked += 1
        else:
            _persist_check(store, row, _result_from_row(store, row), icp,
                           checked_at=row["checked_at"])
    store.conn.commit()
    store.finish_run(run_id, found=found, checked=checked)

    return store.leads(
        min_score=icp.min_score, limit=limit, fresh_only=True,
        search_id=run_id,
    )


def import_gmaps(store: Store, icp: ICP, path, limit: int = 25,
                 fallback_category: str | None = None,
                 progress=None) -> list[dict]:
    """Ingest a user-produced gosom results file as a versioned search, then
    run the normal LeadShoot value-add: live checks, gaps, signals, scoring."""
    from .gmaps import import_results

    run_id = store.start_run(icp.name, icp.area)
    if progress:
        progress(f"search #{run_id}: importing gosom results ({path})")
    found = import_results(store, path, icp.area, search_id=run_id,
                           fallback_category=fallback_category)

    candidates = store.candidates_for_check(run_id, max_age_days=0)
    rows_by_id = {r["id"]: r for r in candidates}
    with_site = {r["id"]: r["osm_website"] for r in candidates if r["osm_website"]}
    if progress:
        progress(f"live-checking {len(with_site)} listed sites "
                 f"({len(candidates) - len(with_site)} have none)")

    def _stream_persist(biz_id: str, result: CheckResult) -> None:
        _persist_check(store, rows_by_id[biz_id], result, icp)
        store.conn.commit()  # live for watchers

    results = run_checks(with_site, progress=progress,
                         on_result=_stream_persist)
    for row in candidates:
        if row["id"] in results:
            continue  # already persisted live
        _persist_check(store, row, CheckResult(status=NO_SITE), icp)
    store.conn.commit()
    store.finish_run(run_id, found=found, checked=len(candidates))
    return store.leads(min_score=icp.min_score, limit=limit,
                       fresh_only=True, search_id=run_id)


def enrich_domain_age(store: Store, icp: ICP, limit: int = 50,
                      progress=None) -> int:
    """RDAP-enrich leads that have a website but no age evidence, then
    rescore. Turns 'age unknown' into a fair maturity rank automatically."""
    import time

    import httpx

    from .rdap import registration_year

    candidates = []
    latest = store.latest_search_id(icp.name)
    for lead in store.leads(min_score=1, limit=limit * 3, fresh_only=False,
                            search_id=latest):
        # fit-mode leads carry no gap flags - a website is the only gate
        if not lead["osm_website"]:
            continue
        if lead["founded_year"] or lead["domain_registered_year"]:
            continue
        candidates.append(lead)
        if len(candidates) >= limit:
            break

    enriched = 0
    with httpx.Client(follow_redirects=True) as client:
        for i, lead in enumerate(candidates):
            year, query = registration_year(store, lead["osm_website"], client)
            if year:
                store.add_signal(lead["id"], K_DOMAIN_YEAR, "rdap",
                                 value=year, url=query,
                                 note="domain registration = age lower bound")
                apply_signal_update(store, icp, lead["id"])
                enriched += 1
            if progress and (i + 1) % 10 == 0:
                progress(f"rdap {i + 1}/{len(candidates)} "
                         f"({enriched} dated)")
            time.sleep(0.4)  # politeness to registry RDAP servers
    return enriched


def recheck(store: Store, icp: ICP, stage: str | None = None,
            progress=None) -> int:
    """Refresh facts for already-known leads. User layer untouched."""
    rows = store.leads(stage=stage, min_score=0, limit=100_000,
                       area=icp.area, categories=icp.categories)
    rows_by_id = {r["id"]: r for r in rows}
    with_site = {r["id"]: r["osm_website"] for r in rows if r["osm_website"]}
    if progress:
        progress(f"rechecking {len(with_site)} sites")

    def _stream_persist(biz_id: str, result: CheckResult) -> None:
        _persist_check(store, rows_by_id[biz_id], result, icp)
        store.conn.commit()  # live for watchers

    results = run_checks(with_site, progress=progress,
                         on_result=_stream_persist)
    for row in rows:
        if row["id"] in results:
            continue  # already persisted live
        _persist_check(store, row, CheckResult(status=NO_SITE), icp)
    store.conn.commit()
    return len(rows)
