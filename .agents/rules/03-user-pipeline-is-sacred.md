# Rule 3 - The user's pipeline is sacred

- `lead_status` (stages, notes), `icp`, and `settings` are user-owned. Engine
  operations (find, recheck, review updates) refresh **facts** and must never
  create, change, or delete pipeline entries. Only an explicit
  `mark`/`update_lead` from the user or their agent may.
- Never re-pitch a worked lead: `find` excludes anything staged
  contacted/interested/won/lost/hidden - don't circumvent that with raw
  `leads` queries unless the user asks for their full pipeline.
- Agents hold no state. Rediscover everything from `status` each session;
  never act from remembered lead lists - they may be stale or another
  agent may have moved the pipeline since.
- Destructive asks (clearing the DB, deleting an ICP, bulk stage changes)
  need explicit user confirmation with the concrete numbers ("this hides
  47 leads - proceed?").
