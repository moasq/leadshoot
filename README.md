<div align="center">
  <img src="assets/logo.png" width="78" alt="LeadShoot" />
  <h1>LeadShoot</h1>
  <p><strong>Whatever you sell to local businesses, your AI agent finds the ones that need it.</strong></p>

  <p>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-1c7d6d?style=flat-square" alt="MIT" /></a>
    <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+" />
    <img src="https://img.shields.io/badge/tests-124%20passing-2e7d5b?style=flat-square" alt="124 tests" />
    <img src="https://img.shields.io/badge/MCP-ready-6b3fa0?style=flat-square" alt="MCP ready" />
    <img src="https://img.shields.io/badge/data-OSM%20%2B%20Overture-7EBC6F?style=flat-square&logo=openstreetmap&logoColor=white" alt="open data" />
  </p>

  <p>
    <a href="#quick-start"><b>Quick start</b></a> ·
    <a href="#-works-with-your-agent">Agents</a> ·
    <a href="#pick-your-niche">Niches</a> ·
    <a href="#how-it-works">How it works</a> ·
    <a href="#data-providers">Providers</a> ·
    <a href="INTEGRATIONS.md">Integrations</a>
  </p>

  <br/>

  <table align="center">
    <tr>
      <td align="center" width="104"><a href="https://claude.com/claude-code"><img src="assets/agents/claude.png" width="58" alt="Claude Code" /></a><br/><sub><b>Claude&nbsp;Code</b></sub></td>
      <td align="center" width="104"><a href="https://openai.com/codex/"><img src="assets/agents/codex.png" width="58" alt="OpenAI Codex" /></a><br/><sub><b>Codex</b></sub></td>
      <td align="center" width="104"><a href="https://antigravity.google"><img src="assets/agents/antigravity.png" width="58" alt="Google Antigravity" /></a><br/><sub><b>Antigravity</b></sub></td>
      <td align="center" width="104"><a href="https://grok.com"><img src="assets/agents/grok.png" width="58" alt="Grok" /></a><br/><sub><b>Grok</b></sub></td>
      <td align="center" width="104"><a href="https://hermes.nousresearch.com"><img src="assets/agents/hermes.png" width="58" alt="Nous Hermes" /></a><br/><sub><b>Hermes</b></sub></td>
      <td align="center" width="104"><a href="https://openclaw.ai"><img src="assets/agents/openclaw.png" width="58" alt="OpenClaw" /></a><br/><sub><b>OpenClaw</b></sub></td>
    </tr>
  </table>

  <p><sub>JSON on every command · seven agent skills · optional MCP server - drive LeadShoot from any agent that runs a shell.</sub></p>

  <br/>

  <img src="assets/map-cluster.png" width="100%" alt="Verified business gaps across Greenwich Village" />
  <p><em>827 businesses in Greenwich Village, every website checked live. Red = a verified reason to call.</em></p>
</div>

## Quick start

No clone, no install. With [uv](https://docs.astral.sh/uv/), one line makes `leadshoot` runnable from anywhere:

```bash
alias leadshoot='uvx --from "leadshoot[all] @ git+https://github.com/moasq/leadshoot" leadshoot'
```

Then point it at a city and go:

```bash
leadshoot icp new --name web --area "Austin, TX" \
    --categories dentist --service website_design --json
leadshoot find --icp web --json      # discover, live-check, rank
leadshoot serve                      # live map of your leads at localhost:8321
```

The first run builds an isolated environment automatically (a few seconds), then it is cached and instant. Want a permanent binary instead? `uv tool install "leadshoot[all] @ git+https://github.com/moasq/leadshoot"`. On PyPI soon, then it is simply `uvx leadshoot`.

Paid lead lists sell everyone the same contacts. **LeadShoot computes yours** - and it's
agent-native the way [Postiz](https://github.com/gitroomhq/postiz-app) is for social:
you tell your AI what you sell, and it runs discovery, verifies every gap against the
real world, ranks by opportunity, and works the pipeline while you keep talking.
Open data, one SQLite file, runs on a laptop.

## ✨ What it does

- ✅ **Tell it what you sell.** A deterministic niche classifier maps your words to *gap mode* (find fixable problems) or *fit mode* (find healthy buyers) - no guessing.
- ✅ **Discovery on open data.** OpenStreetMap and [Overture](https://overturemaps.org/) (~60M places) - no scraping required, no contact list to buy.
- ✅ **Every gap verified.** Flagged sites were fetched and seen failing. Anything inferred is labelled `unverified` and scored lower - verified means verified.
- ✅ **Ranked by opportunity.** Established businesses rank up, brand-new ones down, unknown-age discounted. `enrich` dates them automatically.
- ✅ **Your pipeline stays yours.** Stages and notes live in tables no engine run ever touches.
- ✅ **A live map of the session.** `leadshoot serve` opens a map that repaints itself as data changes - run `find` in a terminal or let an agent add signals over MCP, and pins land as each check commits. No refresh button.
- ✅ **One SQLite file.** No accounts, no cloud, portable - point it at your city.

## 🤖 Works with your agent

Not a SaaS with AI bolted on - a **CLI that speaks JSON**, so any agent that can run a
shell command can drive it. Say *"find cafés in Astoria with dead Instagrams"* and your
agent runs the discovery, the live verification, the scoring, and preps your call list.

**Three ways in, widest first:**

**1. CLI + `--json` - universal.** Every command emits JSON; parse it, don't scrape. Grok,
Hermes, OpenClaw, a bash loop, or cron - if it runs a shell, it runs LeadShoot. No MCP needed.

```bash
leadshoot find --icp x --json
```

**2. `AGENTS.md` + the `.agents/` hub** (7 skills, 4 sub-agents, 5 rules) - agents that read
repo conventions (Claude Code, Codex, Cursor…) pick up how to use it well, automatically.

**3. MCP - optional, for MCP-native agents.**

```bash
claude mcp add leadshoot -- leadshoot mcp     # stdio
leadshoot mcp --transport http              # HTTP :8322/mcp
```

Agents hold no state; everything lives in one SQLite file. Per-client setup:
[INTEGRATIONS.md](INTEGRATIONS.md).

## Pick your niche

| You sell | It finds |
|---|---|
| Websites | businesses with no site, or a dead one |
| Redesigns | outdated WordPress, Wix/GoDaddy templates, slow or non-mobile sites |
| Social media management | accounts gone quiet, tiny audiences |
| Booking / ordering software | busy places you can't book online |
| Reputation management | weak or thin reviews |
| A product - coffee, food, equipment | **healthy buyers**: established, well-reviewed, active |
| Anything else | your own gap mix (`--gaps`) |

Not sure how your niche maps? Ask the engine - it answers deterministically:

```console
$ leadshoot niche "I roast specialty coffee beans"
{"mode": "fit", "categories": ["cafe", "restaurant", "bakery", "hotel"],
 "say": "You sell a product, not a fix - leads are HEALTHY buyers …"}
```

Gap niches hunt fixable problems. Fit niches invert the score: the thriving café
that's worthless to a web designer is a top lead for a coffee roaster.

## What a lead tells you

<table>
<tr>
<td width="55%"><img src="assets/hero-map.png" alt="Lead detail and evidence table" width="100%"/></td>
<td width="45%" align="center"><img src="assets/mobile.png" alt="Mobile view" width="250"/></td>
</tr>
</table>

Every lead explains itself: *what's missing* (verified HTTP error, dead domain,
dormant Instagram), *why it's real* ("34 years in business - proven, and the problem
is verified"), and *what's still unknown* (`age?` `reviews?`).

The full command set (`enrich`, `mark`, `recheck`, `export`, `mcp`, `serve`) is in
[INTEGRATIONS.md](INTEGRATIONS.md).

## How it works

```
ICP → roster (OSM / Overture / BYO) → dedupe vs pipeline → live check → score
```

- Every `find` is a numbered search - results never silently accumulate.
- Verified means verified: flagged sites were fetched and seen failing. Everything inferred is labelled `unverified` and scored lower.
- Established businesses rank up, brand-new ones down, unknowns are kept but discounted - `enrich` dates them automatically.
- Your stages and notes live in separate tables no engine run ever touches.

## Data providers

| | Data | Notes |
|---|---|---|
| `osm` *(default)* | OpenStreetMap | fully open, polite Overpass queries |
| `overture` | [Overture Maps](https://overturemaps.org/), ~60M places | open CDLA license, queried on S3 via DuckDB - ~10× OSM's salon coverage in our Manhattan test |
| `gmaps` | your own [gosom](https://github.com/gosom/google-maps-scraper) run | against Google's ToS - your call, never a default; harvested emails refused |

## Ground rules

Business contacts only - no email harvesting, ever. robots.txt honored on every
fetch. No outreach layer by design; if you email, CAN-SPAM has no B2B exemption.
Full rules: [`.agents/rules/`](.agents/rules/).

## Roadmap

SearXNG confirm-pass for `no_website` · deep link audits (muffet) · screenshot
evidence (shot-scraper) · cross-provider dedupe · Geofabrik country-scale ingest ·
PyPI (`pipx install leadshoot`)

## Contributing

Edit `.agents/` (the single source of truth), run `python scripts/sync_agents.py`,
keep `pytest` green:

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest tests/ -q
```

## License

[MIT](LICENSE). Map data © OpenStreetMap contributors (ODbL); places © Overture Maps
Foundation (CDLA-Permissive-2.0). Agent logos are trademarks of their respective
owners, shown to indicate compatibility.

<div align="center"><sub>Built to be pointed at your city.</sub></div>
