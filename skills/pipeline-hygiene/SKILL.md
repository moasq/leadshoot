---
id: pipeline-hygiene
name: pipeline-hygiene
description: Keep a LeadShoot pipeline healthy - refresh stale facts with recheck, surface leads whose situation changed (site fixed or newly broken), clean out dead entries, and export to the user's CRM. Use for "anything new?", weekly maintenance, before a work session on an old database, or when handing data to another tool.
when_to_use: Trigger phrases - "anything change", "refresh my leads", "clean up the pipeline", "export to my CRM", "is this data stale", scheduled weekly runs.
enabled: true
---
<!-- GENERATED from .agents/skills/pipeline-hygiene/skill.md - edit there and run `python scripts/sync_agents.py`. -->

# Pipeline hygiene - facts fresh, pipeline honest, exits clean

## Staleness check

`leadshoot status` → `last_run.finished_at`. Older than ~30 days = stale:
sites get fixed, businesses close, new ones open. Say so before the user
works old data.

## Refresh (facts only - stages and notes are never touched)

```bash
leadshoot recheck --icp NAME --json            # re-run live checks
leadshoot find --icp NAME --limit 25 --json    # also ingests NEW businesses
```

After a refresh, diff meaningfully for the user:

- **Fixed their site** (gap gone, score dropped): if stage `contacted`+,
  they acted after the pitch - worth a congratulations touch or a `won`
  conversation. If `new`, it self-resolved → suggest `hidden`.
- **Newly broken** (score jumped): fresh, timely reason to call - surface
  these first.
- **Still broken weeks later**: strengthen the note ("down 6+ weeks") -
  urgency honestly earned.

Compare by capturing `leads --json` before and after (id → score/gap_flags)
rather than trusting memory.

## Cleanup (each change needs the user's yes - rule 03)

- Businesses closed/gone → `mark <id> --stage hidden --note "closed"`.
- `lost` leads older than ~6 months: ask whether to revisit (things change)
  or leave closed. Never auto-reopen.
- Duplicate-looking entries (same phone, two OSM objects): keep the richer
  record, hide the other with a cross-reference note.

## Export & handoff

```bash
leadshoot export --format csv --out leads-$(date +%F).csv    # incl. stages/notes
leadshoot export --format json --min-score 50                # filtered handoff
```

CSV columns include reviews_rating/count and the user's stage/note - a CRM
import loses nothing. Keep the ODbL attribution with any dataset that leaves
the tool ("Data © OpenStreetMap contributors (ODbL)").

## Cadence

Suggest (don't nag): weekly `recheck` + monthly `find` per active ICP. The
`weekly-recheck` task in `.agents/tasks/` encodes this for schedulers.
