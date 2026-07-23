---
id: leadshoot
name: leadshoot
description: Drive the LeadShoot engine to find local businesses missing whatever the user sells - websites, redesigns, social media management, booking systems, reputation services, or a custom gap set - and work them as a lead pipeline. Use when the user wants local-business leads or prospects for any local service, asks about businesses lacking something (site, socials, booking, reviews), or wants to see/update their pipeline.
when_to_use: Trigger phrases - "find me leads", "prospects in <city>", "businesses without websites/socials/booking", "who should I pitch my <service> to", "mark X contacted", "show my pipeline", "export my leads".
enabled: true
---
<!-- GENERATED from .agents/skills/leadshoot/skill.md - edit there and run `python scripts/sync_agents.py`. -->

# LeadShoot core - the tool loop

All state is in one SQLite file (`./leadshoot.db` or `$LEADSHOOT_DB` / `--db`).
You hold none. Every command supports `--json` (strictly non-interactive) -
always use it and parse.

## Session start

1. `leadshoot status` → ICPs, pipeline counts (`{"contacted": 3, ...}`), last run.
2. No ICPs → run the `icp-discovery` skill first.
3. Ambiguous ICP (several saved) → ask which, or infer from the request's
   area/categories.

## Core loop

```bash
leadshoot find --icp NAME --limit 25 --json   # discover→check→classify→queue
leadshoot searches --json                     # search history (versions)
leadshoot research-queue --search latest --json
leadshoot leads --search latest --priority high --json
leadshoot show n123 --json                    # full detail incl. review signals
leadshoot mark n123 --stage contacted --note "called, voicemail" --json
leadshoot recheck --icp NAME --json           # refresh facts; stages/notes safe
leadshoot enrich --icp NAME --json            # auto-date leads via RDAP (age floor)
leadshoot export --format csv --out leads.csv
```

- On a `gmaps` ICP, `find` first runs the user's configured Google Maps
  scraper; this is opt-in only because of Google's terms. On other ICPs it
  uses the selected open-data provider.
- `find` live-checks every listed site concurrently: **1–3 minutes on big areas - tell the user
  before running.** It auto-excludes leads already worked (stage ≠ new).
- `find` also **auto-opens the live map** in the user's browser (the
  `live_map` field in its JSON carries the URL) - expected behavior, let it
  happen; the user watches pins land while you keep working. On a headless
  box pass `--no-open` or set `LEADSHOOT_NO_OPEN=1`. `leadshoot ui`
  reopens the map; `leadshoot ui --stop` ends the background server.
- **Every find is a numbered search** (`search_id` in the response). Results
  belong to exactly that search - no accumulation. A business rediscovered
  by a newer search is claimed by it (never duplicated); older searches lose
  it. Scope any listing with `--search N` or `--search latest`.
- New location asked for → save an ICP with that area, run `find` - a new
  numbered search. If a city returns oddly few businesses, the geocoder
  likely picked a small district - retry with the wider form
  ("Muscat Governorate, Oman" not "Muscat, Oman").
- Stages: new → contacted → interested → won | lost | hidden.
- `leadshoot options --json` lists valid categories/services/stages/gaps -
  validate inputs against it instead of guessing.
- The response contains `research_queue`: bounded independent jobs. Use the
  `quick-qualification` skill and run separate leads in parallel when
  supported.

## Presenting leads

Lead: `{priority, priority_reason, evidence, research_status,
research_needed, next_action, name, category, phone, address, gap_flags, confidence,
reviews_rating, reviews_count, social_followers, social_last_post_days,
founded_year, stage, note}`.

- Present high, then medium, then not_sure. State `priority_reason`, evidence,
  and the next action; never invent or expose a numeric score.
- `confidence: unverified` → say "likely/unconfirmed", never assert.
- Maturity is a qualifier: established (3y+) is stronger evidence,
  just-started is riskier, and unknown age stays unknown. Mention
  "est. 2009" when known - it's a trust cue for the user.
- Great reviews + broken/no site is the **hottest** combo - a beloved
  business that's invisible online. Call that out when you see it.
- Keep the OSM attribution line on exported/shown datasets.

## Signals (agent-researched facts)

`leadshoot signal add <id> --key K --source S --value N --json` records what
you researched and reclassifies immediately. Qualification keys: reviews.rating,
reviews.count, social.followers, social.last_post_days,
business.founded_year, and website.official_url (a sourced correction when
the provider missed the site). `leadshoot signal list <id>` shows what's recorded.
If the user asks for signals outside their ICP's targeting, confirm first
(see `icp-discovery`).

## Escalate to sibling skills

ICP creation/refinement → `icp-discovery` · new-result funnel →
`quick-qualification` · reviews → `review-research` ·
maturity & social health → `business-signals` · one-lead dossier →
`business-deep-dive` · writing the pitch → `outreach-prep` · stale data /
CRM handoff → `pipeline-hygiene`.
