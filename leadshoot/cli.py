"""LeadShoot CLI - one of three faces over the same engine (CLI / MCP / REST)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer

from . import OSM_ATTRIBUTION, __version__
from .export import to_csv, to_json
from .icp import CATEGORIES, GAP_WEIGHTS, ICP, SERVICES, infer_gaps
from .pipeline import apply_signal_update, enrich_domain_age
from .pipeline import find_leads as run_find
from .pipeline import import_gmaps as run_import_gmaps
from .pipeline import recheck as run_recheck
from .store import KNOWN_SIGNAL_KEYS, STAGES, Store

_JSON_OPT = typer.Option(False, "--json", help="Machine-readable JSON output "
                                               "(for agents and scripts).")


def _emit(payload) -> None:
    typer.echo(json.dumps(payload, indent=2, default=str))

app = typer.Typer(help="Find the local businesses missing what you sell - "
                       "gaps verified live on open data, ranked by "
                       "opportunity.",
                  no_args_is_help=True)
icp_app = typer.Typer(help="Manage ideal customer profiles (ICPs).",
                      no_args_is_help=True)
app.add_typer(icp_app, name="icp")
review_app = typer.Typer(help="Record review signals researched by you or "
                              "your agent (Google/Yelp/etc. aggregates).",
                         no_args_is_help=True)
app.add_typer(review_app, name="review")
signal_app = typer.Typer(help="Record any researched signal (reviews, social "
                              "activity, founding year, …) and rescore.",
                         no_args_is_help=True)
app.add_typer(signal_app, name="signal")

_DB_OPT = typer.Option(None, "--db", help="Path to the SQLite database "
                                          "(default ./leadshoot.db or $LEADSHOOT_DB).")


def _store(db: str | None) -> Store:
    return Store(db)


def _echo_progress(msg: str) -> None:
    typer.secho(f"  · {msg}", dim=True)


def _require_icp(store: Store, name: str | None) -> ICP:
    icps = store.list_icps()
    if name is None:
        if len(icps) == 1:
            name = icps[0]["name"]
        elif not icps:
            typer.secho("No ICP yet. Create one first:", fg="yellow")
            typer.echo('  leadshoot icp new --name mine --area "Portland, OR" '
                       "--categories dentist,cafe --service website_design")
            raise typer.Exit(1)
        else:
            typer.secho(f"Multiple ICPs - pick one with --icp: "
                        f"{[i['name'] for i in icps]}", fg="yellow")
            raise typer.Exit(1)
    definition = store.get_icp(name)
    if definition is None:
        typer.secho(f"ICP not found: {name}", fg="red")
        raise typer.Exit(1)
    return ICP.from_dict(definition)


def _format_lead(lead: dict, verbose: bool = False) -> str:
    gaps = lead["gap_flags"] or "-"
    conf = " (unverified)" if lead.get("confidence") == "unverified" else ""
    phone = lead.get("phone") or "no phone"
    line = (f"  {lead['score']:>3}  {lead['id']:<12} {lead['name'][:34]:<34} "
            f"{lead['category']:<12} {gaps}{conf}")
    if verbose:
        line += f"\n       {phone} · {lead.get('address') or 'no address'}"
    return line


@app.command()
def version() -> None:
    """Show version."""
    typer.echo(f"leadshoot {__version__}")


@app.command()
def status(db: str = _DB_OPT) -> None:
    """What state does the engine hold? (Agents call this first.)"""
    s = _store(db).status()
    typer.echo(json.dumps(s, indent=2))


@app.command()
def niche(
    description: str = typer.Argument(help='What you sell, in your words - '
                                           'e.g. "I roast specialty coffee" '
                                           'or "we build websites".'),
) -> None:
    """Deterministically map what you sell to a targeting plan.

    Same words in, same plan out - agents call this instead of guessing.
    Returns mode (gaps: find fixable problems | fit: find healthy buyers |
    clarify: answer the listed questions), suggested categories, and what
    still needs asking. JSON always.
    """
    from .niche import identify

    _emit(identify(description).to_dict())


@app.command()
def options(db: str = _DB_OPT) -> None:
    """Valid categories, services (with inferred gap weights), stages, and
    gaps - JSON, for agents discovering what they can ask for."""
    _emit({
        "categories": sorted(CATEGORIES),
        "services": {s: infer_gaps(s) for s in SERVICES},
        "stages": list(STAGES),
        "gaps": sorted(GAP_WEIGHTS),
        "providers": {
            "osm": "OpenStreetMap (default - open data)",
            "overture": "Overture Maps ~60M places (open CDLA license; "
                        "pip install 'leadshoot[overture]')",
            "gmaps": "your own gosom/google-maps-scraper (opt-in; against "
                     "Google ToS - user's informed choice)",
        },
    })


@app.command()
def config(key: str, value: str = typer.Argument(None), db: str = _DB_OPT) -> None:
    """Get or set a setting (contact, overpass_url)."""
    store = _store(db)
    if value is None:
        typer.echo(store.get_setting(key) or "")
    else:
        store.set_setting(key, value)
        typer.echo(f"{key} = {value}")


@icp_app.command("new")
def icp_new(
    name: str = typer.Option(None, help="Short slug, e.g. portland-web."),
    area: str = typer.Option(None, help='Where you work, e.g. "Portland, OR".'),
    categories: str = typer.Option(None, help="Comma list, e.g. dentist,cafe."),
    service: str = typer.Option(None, help=f"What you sell: {sorted(SERVICES)}."),
    exclude_chains: bool = typer.Option(True, help="Skip brands/franchises."),
    min_score: int = typer.Option(30, help="Minimum opportunity score."),
    gaps: str = typer.Option(None, help="Custom comma list of gaps to target "
                                        "(overrides the service default - "
                                        "use when the user confirmed "
                                        "targeting outside their niche)."),
    prefer_established: bool = typer.Option(
        True, help="Rank established businesses above just-started and "
                   "unknown-age ones."),
    provider: str = typer.Option(
        "osm", help="Data provider: osm (default, open data), overture "
                    "(Overture Maps ~60M places, open CDLA license, needs "
                    "leadshoot[overture]), or gmaps (opt-in: your own "
                    "gosom scraper - against Google's ToS, your call)."),
    mode: str = typer.Option(
        "gaps", help="Targeting mode: gaps (find businesses with fixable "
                     "problems) or fit (find healthy buyers for a product/"
                     "supply niche - reviews, activity, and maturity rank "
                     "UP; nothing is flagged). `leadshoot niche` suggests it."),
    as_json: bool = _JSON_OPT,
    db: str = _DB_OPT,
) -> None:
    """Create an ICP. Flags for automation; interactive wizard when omitted."""
    if as_json:
        missing = [f for f, v in [("--name", name), ("--area", area),
                                  ("--categories", categories)] if v is None]
        if missing:
            _emit({"ok": False,
                   "error": f"--json mode is non-interactive; provide {missing}"})
            raise typer.Exit(1)
        service = service or "website_design"
    if name is None:
        name = typer.prompt("Name this ICP (short slug)")
    if service is None:
        typer.echo(f"Services: {', '.join(sorted(SERVICES))}")
        service = typer.prompt("What service do you sell?", default="website_design")
    if area is None:
        area = typer.prompt('Where do you work? (e.g. "Portland, OR")')
    if categories is None:
        typer.echo(f"Known categories: {', '.join(sorted(CATEGORIES))}")
        categories = typer.prompt("Which business types? (comma list)")

    cats = [c for c in categories.split(",") if c.strip()]
    gap_list = [g.strip() for g in gaps.split(",") if g.strip()] if gaps else []
    try:
        icp = ICP(name=name, area=area, categories=cats, service=service,
                  gaps=gap_list, exclude_chains=exclude_chains,
                  min_score=min_score, prefer_established=prefer_established,
                  provider=provider, mode=mode)
    except ValueError as e:
        if as_json:
            _emit({"ok": False, "error": str(e)})
        else:
            typer.secho(str(e), fg="red")
        raise typer.Exit(1)

    store = _store(db)
    store.save_icp(icp.name, icp.to_dict())
    if as_json:
        _emit({"ok": True, "icp": icp.to_dict()})
        return
    weights = ", ".join(f"{g}={w}" for g, w in icp.weights.items())
    typer.secho(f"Saved ICP '{icp.name}'", fg="green")
    typer.echo(f"  area: {icp.area}")
    typer.echo(f"  categories: {', '.join(icp.categories)}")
    typer.echo(f"  gaps targeted ({icp.service}): {weights}")


@icp_app.command("list")
def icp_list(as_json: bool = _JSON_OPT, db: str = _DB_OPT) -> None:
    """List saved ICPs."""
    icps = _store(db).list_icps()
    if as_json:
        _emit(icps)
        return
    if not icps:
        typer.echo("No ICPs saved.")
        return
    for icp in icps:
        typer.echo(f"  {icp['name']:<20} {icp['area']:<24} "
                   f"{','.join(icp['categories'])}")


@icp_app.command("show")
def icp_show(name: str, db: str = _DB_OPT) -> None:
    """Show one ICP as JSON."""
    definition = _store(db).get_icp(name)
    if definition is None:
        typer.secho(f"ICP not found: {name}", fg="red")
        raise typer.Exit(1)
    typer.echo(json.dumps(definition, indent=2))


@app.command()
def find(
    icp: str = typer.Option(None, "--icp", help="ICP name (optional if only one)."),
    limit: int = typer.Option(25, help="Max leads to return."),
    max_age_days: int = typer.Option(30, help="Recheck sites older than this."),
    as_json: bool = _JSON_OPT,
    db: str = _DB_OPT,
) -> None:
    """Find fresh leads: pull roster, live-check sites, score gaps, rank."""
    store = _store(db)
    profile = _require_icp(store, icp)
    if as_json:
        leads = run_find(store, profile, limit=limit, max_age_days=max_age_days)
        _emit({"attribution": OSM_ATTRIBUTION, "icp": profile.name,
               "search_id": store.latest_run_id(),
               "count": len(leads), "leads": leads})
        return
    typer.secho(f"Finding leads for '{profile.name}' in {profile.area} …",
                bold=True)
    leads = run_find(store, profile, limit=limit, max_age_days=max_age_days,
                     progress=_echo_progress)
    typer.secho(f"  search #{store.latest_run_id()} - this search's results "
                f"(older searches: leadshoot searches)", dim=True)
    if not leads:
        typer.echo("No leads at or above min_score. Try more categories, a "
                   "bigger area, or a lower --min-score on the ICP.")
        return
    typer.echo(f"\n  SCORE ID           NAME{'':<32}CATEGORY     GAPS")
    for lead in leads:
        typer.echo(_format_lead(lead, verbose=True))
    typer.echo(f"\n{len(leads)} leads. Next: leadshoot mark <ID> --stage contacted")
    if profile.provider == "overture":
        from .overture import ATTRIBUTION as OVERTURE_ATTRIBUTION

        typer.secho(OVERTURE_ATTRIBUTION, dim=True)
    else:
        typer.secho(OSM_ATTRIBUTION, dim=True)


@app.command("import-gmaps")
def import_gmaps_cmd(
    file: str = typer.Argument(help="gosom results file (.json / .csv) "
                                    "you produced yourself."),
    icp: str = typer.Option(None, "--icp", help="ICP for area + scoring."),
    category: str = typer.Option(None, help="Fallback LeadShoot category for "
                                            "records whose Google category "
                                            "can't be mapped."),
    limit: int = typer.Option(25),
    as_json: bool = _JSON_OPT,
    db: str = _DB_OPT,
) -> None:
    """Import gosom/google-maps-scraper results as a versioned search.

    You run gosom yourself (CLI, docker, or its web UI) - scraping Google
    Maps is against Google's ToS; your choice, your responsibility. LeadShoot
    then adds its value: live website checks, gap scoring, review signals
    (rating/count land automatically, source=google), and your pipeline.
    Harvested emails in the file are refused (rule 01).
    """
    if not Path(file).exists():
        if as_json:
            _emit({"ok": False, "error": f"file not found: {file}"})
        else:
            typer.secho(f"File not found: {file}", fg="red")
        raise typer.Exit(1)
    store = _store(db)
    profile = _require_icp(store, icp)
    if as_json:
        rows = run_import_gmaps(store, profile, file, limit=limit,
                                fallback_category=category)
        _emit({"attribution": "Imported data: Google Maps via user-run "
                              "gosom scraper", "icp": profile.name,
               "count": len(rows), "leads": rows})
        return
    typer.secho(f"Importing gosom results for '{profile.name}' …", bold=True)
    rows = run_import_gmaps(store, profile, file, limit=limit,
                            fallback_category=category,
                            progress=_echo_progress)
    typer.echo(f"\n  SCORE ID           NAME{'':<32}CATEGORY     GAPS")
    for lead in rows:
        typer.echo(_format_lead(lead, verbose=True))
    typer.echo(f"\n{len(rows)} leads from import. "
               f"Next: leadshoot mark <ID> --stage contacted")


@app.command()
def leads(
    stage: str = typer.Option(None, help=f"Filter by stage: {STAGES}."),
    gap: str = typer.Option(None, help="Filter by gap flag, e.g. broken_site."),
    min_score: int = typer.Option(0, help="Minimum score."),
    limit: int = typer.Option(50),
    search: str = typer.Option(None, help="Scope to one search version: "
                                          "a number, or 'latest'."),
    as_json: bool = _JSON_OPT,
    db: str = _DB_OPT,
) -> None:
    """List leads already in the database (your working pipeline)."""
    store = _store(db)
    search_id = None
    if search is not None:
        search_id = store.latest_run_id() if search == "latest" else int(search)
    rows = store.leads(stage=stage, gap=gap, min_score=min_score,
                       limit=limit, search_id=search_id)
    if as_json:
        _emit({"count": len(rows), "leads": rows})
        return
    if not rows:
        typer.echo("Nothing matches. Run `leadshoot find` first?")
        return
    typer.echo(f"  SCORE ID           NAME{'':<32}CATEGORY     GAPS")
    for lead in rows:
        stage_txt = f" [{lead['stage']}]" if lead["stage"] != "new" else ""
        typer.echo(_format_lead(lead) + stage_txt)


@app.command()
def mark(
    business_id: str = typer.Argument(help="Lead id, e.g. n4005935323."),
    stage: str = typer.Option(None, help=f"One of {STAGES}."),
    note: str = typer.Option(None, help="Free-text note."),
    as_json: bool = _JSON_OPT,
    db: str = _DB_OPT,
) -> None:
    """Update your pipeline: stage and/or note. Never touched by re-runs."""
    def fail(msg: str) -> None:
        if as_json:
            _emit({"ok": False, "error": msg})
        else:
            typer.secho(msg, fg="red")
        raise typer.Exit(1)

    if stage is None and note is None:
        fail("Provide --stage and/or --note.")
    try:
        ok = _store(db).mark(business_id, stage=stage, note=note)
    except ValueError as e:
        fail(str(e))
    if not ok:
        fail(f"No business with id {business_id}")
    if as_json:
        _emit({"ok": True, "business_id": business_id,
               "stage": stage, "note": note})
    else:
        typer.secho("Updated.", fg="green")


@signal_app.command("add")
def signal_add(
    business_id: str = typer.Argument(help="Lead id, e.g. n4005935323."),
    key: str = typer.Option(..., help=f"Signal key. Scored keys: "
                                      f"{', '.join(KNOWN_SIGNAL_KEYS)}. "
                                      f"Other keys are stored (extensible) "
                                      f"but don't affect the score."),
    source: str = typer.Option(..., help="Where observed: google, instagram, "
                                         "facebook, website, registry, …"),
    value: float = typer.Option(None, help="Numeric value (rating, count, "
                                           "followers, days, year)."),
    text: str = typer.Option(None, help="Text value for non-numeric signals."),
    url: str = typer.Option(None, help="Public source URL."),
    note: str = typer.Option("", help="Short context note."),
    icp: str = typer.Option(None, "--icp", help="ICP used for rescoring."),
    as_json: bool = _JSON_OPT,
    db: str = _DB_OPT,
) -> None:
    """Record one researched signal and rescore the lead.

    Aggregates and public facts only - never personal data. Unknown stays
    unknown: absence of a signal is never a gap, though unknown founding
    age ranks below established businesses.
    """
    store = _store(db)
    if not store.add_signal(business_id, key, source, value=value, text=text,
                            url=url, note=note):
        if as_json:
            _emit({"ok": False, "error": f"No business with id {business_id}"})
        else:
            typer.secho(f"No business with id {business_id}", fg="red")
        raise typer.Exit(1)
    profile = _require_icp(store, icp)
    biz = apply_signal_update(store, profile, business_id)
    if as_json:
        _emit({"ok": True, "lead": biz})
        return
    typer.secho(f"Recorded {key} from {source}. Score: {biz['score']} "
                f"(gaps: {biz['gap_flags'] or '-'})", fg="green")


@signal_app.command("list")
def signal_list(business_id: str, as_json: bool = _JSON_OPT,
                db: str = _DB_OPT) -> None:
    """Show all recorded signals for a lead."""
    signals = _store(db).signals_for(business_id)
    if as_json:
        _emit(signals)
        return
    if not signals:
        typer.echo("No signals recorded.")
        return
    for s in signals:
        val = s["value"] if s["value"] is not None else (s["value_text"] or "-")
        typer.echo(f"  {s['key']:<24} {s['source']:<12} {val!s:<10} "
                   f"{s['url'] or ''}")


@review_app.command("add")
def review_add(
    business_id: str = typer.Argument(help="Lead id, e.g. n4005935323."),
    source: str = typer.Option(..., help="Where the numbers came from: "
                                         "google, yelp, tripadvisor, …"),
    rating: float = typer.Option(None, min=0, max=5,
                                 help="Aggregate star rating (0-5)."),
    count: int = typer.Option(None, min=0, help="Total review count."),
    url: str = typer.Option(None, help="Public profile URL."),
    note: str = typer.Option("", help="Short context note."),
    icp: str = typer.Option(None, "--icp", help="ICP used for rescoring."),
    as_json: bool = _JSON_OPT,
    db: str = _DB_OPT,
) -> None:
    """Record an aggregate review signal for a lead and rescore it.

    Record only business-level aggregates (rating, count, URL) - never
    review text dumps or reviewer identities.
    """
    store = _store(db)
    if not store.add_review_signal(business_id, source, rating=rating,
                                   review_count=count, url=url, note=note):
        if as_json:
            _emit({"ok": False, "error": f"No business with id {business_id}"})
        else:
            typer.secho(f"No business with id {business_id}", fg="red")
        raise typer.Exit(1)
    profile = _require_icp(store, icp)
    biz = apply_signal_update(store, profile, business_id)
    if as_json:
        _emit({"ok": True, "lead": biz})
        return
    typer.secho(f"Recorded {source} signal. New score: {biz['score']} "
                f"(gaps: {biz['gap_flags'] or '-'})", fg="green")


@review_app.command("list")
def review_list(business_id: str, as_json: bool = _JSON_OPT,
                db: str = _DB_OPT) -> None:
    """Show recorded review signals for a lead."""
    signals = _store(db).review_signals_for(business_id)
    if as_json:
        _emit(signals)
        return
    if not signals:
        typer.echo("No review signals recorded.")
        return
    for s in signals:
        typer.echo(f"  {s['key']:<16} {s['source']:<14} {s['value']!s:<8} "
                   f"{s['url'] or ''}")


@app.command()
def searches(limit: int = typer.Option(20), as_json: bool = _JSON_OPT,
             db: str = _DB_OPT) -> None:
    """Search history - every find is a numbered search version."""
    runs = _store(db).list_runs(limit=limit)
    if as_json:
        _emit(runs)
        return
    if not runs:
        typer.echo("No searches yet. Run `leadshoot find`.")
        return
    typer.echo("  #    ICP                  AREA                     FOUND  CHECKED  WHEN")
    for r in runs:
        typer.echo(f"  {r['id']:<4} {(r['icp_name'] or '-'):<20} "
                   f"{(r['area'] or '-'):<24} {r['found'] or 0:>5}  "
                   f"{r['checked'] or 0:>7}  {r['started_at'] or ''}")


@app.command()
def show(business_id: str, as_json: bool = _JSON_OPT,
         db: str = _DB_OPT) -> None:
    """Full detail for one lead: facts, gaps, reviews, pipeline stage."""
    biz = _store(db).get_business(business_id)
    if biz is None:
        if as_json:
            _emit({"ok": False, "error": f"No business with id {business_id}"})
        else:
            typer.secho(f"No business with id {business_id}", fg="red")
        raise typer.Exit(1)
    _emit(biz)


@app.command()
def enrich(
    icp: str = typer.Option(None, "--icp"),
    limit: int = typer.Option(50, help="Max leads to enrich this run."),
    as_json: bool = _JSON_OPT,
    db: str = _DB_OPT,
) -> None:
    """Date leads automatically via RDAP (open protocol, no keys).

    A domain's registration year is a lower bound on business age; leads
    with unknown age get fairly ranked by the maturity qualifier.
    """
    store = _store(db)
    profile = _require_icp(store, icp)
    if as_json:
        n = enrich_domain_age(store, profile, limit=limit)
        _emit({"enriched": n})
        return
    n = enrich_domain_age(store, profile, limit=limit,
                          progress=_echo_progress)
    typer.secho(f"Dated {n} leads via domain registration (RDAP).",
                fg="green")


@app.command()
def recheck(
    icp: str = typer.Option(None, "--icp"),
    stage: str = typer.Option(None, help="Only recheck leads in this stage."),
    as_json: bool = _JSON_OPT,
    db: str = _DB_OPT,
) -> None:
    """Refresh site facts (did they fix it?). Stages and notes are untouched."""
    store = _store(db)
    profile = _require_icp(store, icp)
    if as_json:
        n = run_recheck(store, profile, stage=stage)
        _emit({"rechecked": n})
        return
    n = run_recheck(store, profile, stage=stage, progress=_echo_progress)
    typer.secho(f"Rechecked {n} leads.", fg="green")


@app.command()
def export(
    fmt: str = typer.Option("csv", "--format", help="csv or json."),
    out: str = typer.Option(None, help="Output path (default stdout)."),
    stage: str = typer.Option(None),
    min_score: int = typer.Option(0),
    db: str = _DB_OPT,
) -> None:
    """Export leads (with stages/notes) for your CRM."""
    rows = _store(db).leads(stage=stage, min_score=min_score, limit=100_000)
    payload = to_csv(rows) if fmt == "csv" else to_json(rows)
    if out:
        Path(out).write_text(payload)
        typer.secho(f"Wrote {len(rows)} leads to {out}", fg="green")
    else:
        typer.echo(payload)
    typer.secho(f"# {OSM_ATTRIBUTION}", dim=True, err=True)


@app.command()
def serve(
    port: int = typer.Option(8321),
    host: str = typer.Option("127.0.0.1"),
    db: str = _DB_OPT,
) -> None:
    """Serve the REST API + local map UI."""
    try:
        import uvicorn

        from .api import create_app
    except ImportError:
        typer.secho("Server extras missing: pip install 'leadshoot[server]'",
                    fg="red")
        raise typer.Exit(1)
    typer.echo(f"LeadShoot UI on http://{host}:{port}")
    uvicorn.run(create_app(db), host=host, port=port, log_level="warning")


@app.command()
def mcp(
    transport: str = typer.Option("stdio", help="stdio (default) or http "
                                                "(streamable HTTP)."),
    host: str = typer.Option("127.0.0.1", help="Bind host for http transport."),
    port: int = typer.Option(8322, help="Port for http transport."),
    db: str = _DB_OPT,
) -> None:
    """Run the MCP server for Claude, Cursor, Codex, or any MCP client.

    stdio for local clients; http exposes streamable HTTP at /mcp for
    clients that connect over the network.
    """
    try:
        from .mcp_server import build_server
    except ImportError:
        typer.secho("MCP extras missing: pip install 'leadshoot[mcp]'", fg="red")
        raise typer.Exit(1)
    server = build_server(db, host=host, port=port)
    if transport == "stdio":
        server.run()
    elif transport in ("http", "streamable-http"):
        typer.echo(f"LeadShoot MCP (streamable HTTP) on http://{host}:{port}/mcp")
        server.run(transport="streamable-http")
    else:
        typer.secho("transport must be stdio or http", fg="red")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
