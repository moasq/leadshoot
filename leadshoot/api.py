"""REST API + static web UI. A thin lens: every route is a store/pipeline call."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import OSM_ATTRIBUTION, __version__
from .export import to_csv, to_json
from .icp import ICP
from .pipeline import apply_signal_update, enrich_domain_age
from .pipeline import find_leads as run_find
from .pipeline import import_gmaps as run_import_gmaps
from .pipeline import recheck as run_recheck
from .store import STAGES, Store

WEB_DIR = Path(__file__).parent / "web"


class ICPBody(BaseModel):
    name: str
    area: str
    categories: list[str]
    service: str = "website_design"
    exclude_chains: bool = True
    min_score: int = 30
    provider: str = "osm"
    mode: str = "gaps"


class ImportBody(BaseModel):
    path: str
    icp_name: str | None = None
    fallback_category: str | None = None
    limit: int = 25


class LeadPatch(BaseModel):
    stage: str | None = None
    note: str | None = None


class SearchBody(BaseModel):
    icp_name: str | None = None
    limit: int = 25


class ReviewBody(BaseModel):
    source: str
    rating: float | None = None
    review_count: int | None = None
    url: str | None = None
    note: str = ""
    icp_name: str | None = None


class SignalBody(BaseModel):
    key: str
    source: str
    value: float | None = None
    text: str | None = None
    url: str | None = None
    note: str = ""
    icp_name: str | None = None


def create_app(db: str | None = None) -> FastAPI:
    app = FastAPI(title="LeadShoot", version=__version__)

    def store() -> Store:
        return Store(db)

    def _icp(s: Store, name: str | None) -> ICP:
        if name is None:
            icps = s.list_icps()
            if len(icps) != 1:
                raise HTTPException(400, "specify icp_name")
            name = icps[0]["name"]
        d = s.get_icp(name)
        if d is None:
            raise HTTPException(404, f"ICP not found: {name}")
        return ICP.from_dict(d)

    @app.get("/api/status")
    def api_status() -> dict:
        return store().status()

    @app.get("/api/options")
    def api_options() -> dict:
        """The engine's vocabulary - same payload as `leadshoot options` and
        MCP list_options. The UI builds its filters from this, so every
        gap the engine can compute is filterable, with nothing hardcoded."""
        from .icp import CATEGORIES, GAP_WEIGHTS, SERVICES, infer_gaps

        return {
            "categories": sorted(CATEGORIES),
            "services": {s: infer_gaps(s) for s in SERVICES},
            "stages": list(STAGES),
            "gaps": sorted(GAP_WEIGHTS),
        }

    @app.get("/api/niche")
    def api_niche(q: str) -> dict:
        from .niche import identify

        return identify(q).to_dict()

    @app.get("/api/leads")
    def api_leads(stage: str | None = None, gap: str | None = None,
                  min_score: int = 0, limit: int = 500,
                  search_id: int | None = None) -> dict:
        rows = store().leads(stage=stage, gap=gap, min_score=min_score,
                             limit=limit, search_id=search_id)
        return {"attribution": OSM_ATTRIBUTION, "count": len(rows),
                "leads": rows}

    @app.get("/api/searches")
    def api_searches(limit: int = 50) -> list[dict]:
        return store().list_runs(limit=limit)

    @app.get("/api/facets")
    def api_facets(search_id: int | None = None) -> dict:
        """Gaps + stages present in the current scope, with counts - the
        UI's filter options are built from this, so it offers only what the
        data actually contains (not the full vocabulary)."""
        return store().facets(search_id)

    @app.get("/api/stream")
    async def api_stream(request: Request) -> StreamingResponse:
        """Reactive session feed. The UI (or any watcher) holds this SSE
        stream open; whenever anything commits to the DB - a find running in
        the CLI, an agent adding signals over MCP, a stage change - a
        `change` event fires and the client re-reads what it renders.
        The engine stays write-only; this is a read-side pulse."""

        async def gen():
            s = store()
            last: str | None = None
            idle = 0.0
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    token = s.change_token()
                    if token != last:
                        last = token
                        payload = {"token": token,
                                   "latest_search": s.latest_run_id()}
                        yield ("event: change\n"
                               f"data: {json.dumps(payload)}\n\n")
                        idle = 0.0
                    else:
                        idle += 1.0
                        if idle >= 15:  # keep proxies from closing us
                            yield ": keep-alive\n\n"
                            idle = 0.0
                    await asyncio.sleep(1.0)
            finally:
                s.close()

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.get("/api/leads/{business_id}")
    def api_get_lead(business_id: str) -> dict:
        biz = store().get_business(business_id)
        if biz is None:
            raise HTTPException(404, f"no business {business_id}")
        return biz

    @app.post("/api/leads/{business_id}/reviews")
    def api_add_review(business_id: str, body: ReviewBody) -> dict:
        s = store()
        if not s.add_review_signal(business_id, body.source,
                                   rating=body.rating,
                                   review_count=body.review_count,
                                   url=body.url, note=body.note):
            raise HTTPException(404, f"no business {business_id}")
        icp = _icp(s, body.icp_name)
        return apply_signal_update(s, icp, business_id)

    @app.post("/api/leads/{business_id}/signals")
    def api_add_signal(business_id: str, body: SignalBody) -> dict:
        s = store()
        if not s.add_signal(business_id, body.key, body.source,
                            value=body.value, text=body.text,
                            url=body.url, note=body.note):
            raise HTTPException(404, f"no business {business_id}")
        icp = _icp(s, body.icp_name)
        return apply_signal_update(s, icp, business_id)

    @app.patch("/api/leads/{business_id}")
    def api_mark(business_id: str, body: LeadPatch) -> dict:
        if body.stage is not None and body.stage not in STAGES:
            raise HTTPException(400, f"stage must be one of {STAGES}")
        ok = store().mark(business_id, stage=body.stage, note=body.note)
        if not ok:
            raise HTTPException(404, f"no business {business_id}")
        return {"ok": True}

    @app.post("/api/leads/search")
    def api_search(body: SearchBody) -> dict:
        s = store()
        icp = _icp(s, body.icp_name)
        leads = run_find(s, icp, limit=body.limit)
        return {"attribution": OSM_ATTRIBUTION, "count": len(leads),
                "leads": leads}

    @app.post("/api/import/gmaps")
    def api_import_gmaps(body: ImportBody) -> dict:
        s = store()
        icp = _icp(s, body.icp_name)
        try:
            leads = run_import_gmaps(s, icp, body.path, limit=body.limit,
                                     fallback_category=body.fallback_category)
        except FileNotFoundError:
            raise HTTPException(404, f"file not found: {body.path}")
        return {"count": len(leads), "leads": leads}

    @app.post("/api/leads/recheck")
    def api_recheck(body: SearchBody) -> dict:
        s = store()
        icp = _icp(s, body.icp_name)
        return {"rechecked": run_recheck(s, icp)}

    @app.post("/api/leads/enrich")
    def api_enrich(body: SearchBody) -> dict:
        s = store()
        icp = _icp(s, body.icp_name)
        return {"enriched": enrich_domain_age(s, icp, limit=body.limit)}

    @app.get("/api/icps")
    def api_icps() -> list[dict]:
        return store().list_icps()

    @app.post("/api/icps")
    def api_save_icp(body: ICPBody) -> dict:
        try:
            icp = ICP(**body.model_dump())
        except ValueError as e:
            raise HTTPException(400, str(e))
        s = store()
        s.save_icp(icp.name, icp.to_dict())
        return icp.to_dict()

    @app.get("/api/export", response_class=PlainTextResponse)
    def api_export(format: str = "csv", stage: str | None = None,
                   min_score: int = 0) -> str:
        rows = store().leads(stage=stage, min_score=min_score, limit=100_000)
        return to_csv(rows) if format == "csv" else to_json(rows)

    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    return app
