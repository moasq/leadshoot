# Rule 5 - Engineering invariants (for agents changing this repo)

1. **Facts vs. workflow.** `businesses`/`runs`/`areas`/`review_signals` are
   fact tables; `lead_status`/`icp`/`settings` are user-owned. Ingest and
   recheck must never write the user-owned tables. Tests enforce this.
2. **The trust ladder is load-bearing** (see Rule 2). Changes to
   `check.py`/`score.py` must keep: bot-defense ≠ broken, blocked ≠ judged,
   unverified discounted, review-unknown ≠ gap.
3. **Politeness contracts.** Nominatim: one geocode per area, cached,
   identifiable UA. Overpass: small ad-hoc queries, 1s pauses, backoff on
   429/504, `overpass_url` setting honored. Live checks: robots.txt, homepage
   only, bounded concurrency. Bulk ingestion belongs to Geofabrik extracts.
4. **Permissive licenses only.** MIT/BSD/Apache dependencies. No GPL/AGPL,
   no non-commercial, no gated APIs. ODbL attribution stays on exports/UI.
5. **Agent parity.** Every new capability lands in all three faces - CLI
   (with `--json`, non-interactive), MCP tool, REST route - backed by the
   same engine function, plus a test.
6. **`.agents/` is the single source of truth** for agent-facing docs.
   Root `AGENTS.md`, `.claude/skills/`, `.claude/agents/`, and
   `skills/leadshoot/` are GENERATED - edit `.agents/` and run
   `python scripts/sync_agents.py`. Never edit generated files directly.
7. Tests: pytest, tmp DBs, no network. `.venv/bin/python -m pytest tests/ -q`
   must be green before any change is done.
