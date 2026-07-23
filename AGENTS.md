<!-- GENERATED from .agents/agents.md - edit there and run `python scripts/sync_agents.py`. -->
# LeadShoot - agent guide

LeadShoot finds local businesses that are **missing whatever the user sells**.
The user's service defines what counts as a lead, via two modes. **Gap
mode**: their service fixes something - websites (no/broken/insecure site),
redesigns (outdated tech, DIY builders, slow or non-mobile sites), social
media management (dormant accounts, tiny audiences), booking/ordering
software, reputation management (weak or thin reviews), or any custom gap
set. **Fit mode**: they sell a product or supply (coffee, food, equipment,
B2B services) - leads are *healthy buyers*, where good reviews, activity,
and maturity rank UP and nothing is flagged. The deterministic
`leadshoot niche` classifier maps the user's words to the right mode - use
it, never guess. "Businesses without websites" is one niche, not the
product; never present the tool as website-only. Discovery runs on open
data, every gap is verified or honestly labeled unverified, and results
rank by opportunity score.

**This directory (`.agents/`) is the single source of truth** for everything
agent-facing. Root `AGENTS.md`, `.claude/skills/`, `.claude/agents/`, and
`skills/leadshoot/` are generated from here by `python scripts/sync_agents.py`
- edit here, then sync. The hub:

| Path | What it holds |
|---|---|
| `agents.md` | This file - the canonical guide |
| `system-prompt.md` | Condensed operating identity for agents driving LeadShoot |
| `rules/01…05` | Binding rules: data ethics · verified-means-verified · user pipeline is sacred · outreach compliance · engineering invariants |
| `skills/` | Playbooks: `leadshoot` (core), `icp-discovery`, `review-research`, `business-signals`, `business-deep-dive`, `outreach-prep`, `pipeline-hygiene` |
| `agents/` | Sub-agents: `lead-scout`, `review-analyst`, `business-researcher`, `pitch-writer` |
| `tasks/` | Recurring work: `weekly-recheck` |
| `mcp.json` | MCP registration (`leadshoot mcp`) |

---

## Part 1 - Using LeadShoot as a tool

**You hold no state.** Everything lives in one SQLite file (`./leadshoot.db`,
or `$LEADSHOOT_DB` / `--db`). Rediscover it every session.

**Session protocol:**
1. `leadshoot status` - ICPs, pipeline counts, last run. Fresh install (no
   ICPs) → run the `icp-discovery` skill: FIRST call
   `leadshoot niche "<their words>"` (deterministic classifier: gaps niche /
   fit niche / clarify - never guess the mapping yourself), then elicit
   what its plan says is missing; then `leadshoot icp new … --json`.
   **Fit niches** (physical products, supplies, B2B services - e.g. selling
   coffee to cafés): save with `--mode fit` - healthy buyers rank UP
   (reviews, activity, maturity), nothing is flagged as a problem.
2. `leadshoot find --icp NAME --limit 25 --json` - pulls the OSM roster,
   live-checks every website, merges review gaps, scores, ranks. 1–3 min on
   big areas; warn the user. **`find` auto-opens the live map** in the
   user's browser (background server per db, reused; `live_map` in the JSON
   carries the URL) - the user watches pins land while you work. Headless/
   CI: `--no-open` or `LEADSHOOT_NO_OPEN=1`. Reopen anytime with
   `leadshoot ui`; `leadshoot ui --stop` ends the background server.
   **Every find is a numbered search** (its
   version, returned as `search_id`): results are scoped to exactly what
   that search found - they never accumulate. A business rediscovered by a
   newer search is *claimed* by it (never duplicated); older searches lose
   it. History: `leadshoot searches`.
3. Work leads: `leads` (filter `--stage --gap --min-score --search N|latest`)
   · `show <id>` · `mark <id> --stage --note` · `review add <id> --source …
   --rating … --count …` · `recheck` · `export --format csv`.
4. New location requested → new ICP (or re-save the same name with the new
   area), then `find` - a fresh numbered search. Geocoding tip: if a city
   search returns suspiciously few results, the name may have resolved to a
   small district - retry with the wider form ("Muscat Governorate, Oman"
   instead of "Muscat, Oman").

**Every command takes `--json`** (strictly non-interactive) - parse, don't
scrape text. `leadshoot options` lists valid categories, services (with gap
weights), stages, and gaps.

**Services → targeted gaps:** `website_design` (no_website, broken_site,
no_ssl) · `redesign` (broken_site, not_mobile, no_ssl) · `booking_setup`
(no_booking, …) · `reputation_management` (weak_reviews, few_reviews, …) ·
`social_media` (inactive_social, weak_social, …) · `general` (all).
Custom targeting: `--gaps` on `icp new` - but **if the user asks for
signals/leads outside their ICP's niche, confirm before expanding it**
(permanent `--gaps` change vs one-off research; see `icp-discovery`).

**Reading results:** `score` 0–100 hottest first; `gap_flags` is the reason
to reach out; `confidence: verified` = observed by the engine or sourced
signal data; `unverified` = inferred (missing OSM tag, unreachable host) -
present as unconfirmed. Signal fields (`reviews_*`, `social_followers`,
`social_last_post_days`, `founded_year`) appear once recorded; absence of
signals means *unknown*, never a gap. **Maturity is a qualifier, not a
gap:** established (3y+) businesses rank up, just-started (<1y) rank down
(users avoid the risk), unknown age is kept but discounted
(`prefer_established` on the ICP, default on).

**Data providers:** the ICP's `provider` picks discovery:
- `osm` (default) - OpenStreetMap via Overpass, fully open, lightest.
- `overture` - Overture Maps (~60M places, CDLA-Permissive-2.0, no ToS
  tension): DuckDB queries the public S3 GeoParquet release in place.
  Needs `pip install 'leadshoot[overture]'`. Measured vs OSM in the same
  Manhattan bbox: ~10× the salons, 91% of records carrying a website.
  Recommend it when the user wants coverage but not the gmaps tradeoff.
- `gmaps` (opt-in) - the user's own gosom/google-maps-scraper; against
  Google's ToS, their informed choice (rule 01). Flow: user runs gosom or
  you auto-run their configured binary → `leadshoot import-gmaps results.json
  --icp X` (or `find` on a gmaps ICP). Google review aggregates auto-land
  as signals. Never enable gmaps without the user explicitly choosing it.

**Signals flow** (the engine itself never scrapes Google/Yelp/Instagram): you
research public profiles with your own web tools (`review-research` and
`business-signals` skills carry the source maps and methods), then persist
aggregates - the lead rescored on every add:

```bash
leadshoot review add n123 --source google --rating 3.1 --count 47 --json
leadshoot signal add n123 --key business.founded_year --source website --value 2009 --json
leadshoot signal add n123 --key social.last_post_days --source instagram --value 180 --json
```

Scored keys: `reviews.rating`, `reviews.count`, `social.followers`,
`social.last_post_days`, `business.founded_year`,
`domain.registered_year` (auto via `leadshoot enrich` - RDAP domain lookups,
open protocol; a maturity *floor* when founding is unknown). The live check
also auto-detects the site platform (`site.builder` text signal) and three
more gaps: `outdated_tech` (WordPress <6 / Joomla 3 / Drupal 7),
`diy_builder` (Wix/Squarespace/GoDaddy/Weebly/Jimdo/Duda), `slow_site`
(>4s). Run `leadshoot enrich --icp X` after a find so unknown-age leads get
fairly ranked. Other keys are stored (extensible) but unscored. Aggregates
and business facts only - never review text, reviewer identities, or
personal data.

**MCP:** `leadshoot mcp` (stdio) or `--transport http --port 8322` (streamable
HTTP at `/mcp`). Tools: status, list_options, save_icp, list_icps,
find_leads, list_leads, get_lead, update_lead, add_review_signal, recheck,
export_leads. REST + OpenAPI: `leadshoot serve` → `/api/*`, `/openapi.json`,
map UI at `/`. Per-client setup: `INTEGRATIONS.md`.

**Binding rules** (full text in `.agents/rules/`): business facts from clean
sources only, aggregates not review text, no email harvesting (01); never
oversell unverified gaps, bot-defense ≠ broken (02); never write the user's
stages/notes except by explicit request, never re-pitch worked leads (03);
CAN-SPAM has no B2B exemption, honest pitches only (04).

---

## Part 2 - Developing this repo

**Setup & verify:**
```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -q        # must stay green; no network in tests
python scripts/sync_agents.py               # after editing .agents/
```

**Layout:** `leadshoot/store.py` (SQLite: fact tables vs user-owned tables),
`icp.py` (profiles, category dictionary, services), `ingest.py`
(Nominatim/Overpass, politeness), `check.py` (live site checker),
`score.py` (gaps + opportunity score), `pipeline.py` (orchestration),
`cli.py` (Typer), `mcp_server.py` (FastMCP), `api.py` (FastAPI + `web/`).

**Invariants - binding, full text in `rules/05-engineering-invariants.md`:**
facts vs. workflow split; the verified trust ladder; OSM politeness
contracts; permissive licenses only; agent parity (CLI+MCP+REST together);
`.agents/` is SSOT and generated files are never hand-edited; tests green
before done.
