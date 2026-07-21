---
id: weekly-recheck
name: weekly-recheck
intervalMinutes: 10080
---

# Weekly pipeline refresh

Run the `pipeline-hygiene` skill against every saved ICP:

1. `leadshoot status` → for each ICP name:
2. Capture `leadshoot leads --json` (id → score/gap_flags) as the before-state.
3. `leadshoot recheck --icp <name> --json`.
4. Diff and report ONLY meaningful changes:
   - leads whose site got FIXED (gap gone) - if staged contacted+, suggest a
     follow-up touch; if new, suggest hiding.
   - leads newly BROKEN (score jumped) - timely reasons to call, surface first.
5. Never change stages or notes yourself; propose changes to the user.

If the last full `find` is older than 30 days, recommend one (it also picks
up newly opened businesses) - but don't run it unattended; it hits the
network harder than a recheck.
