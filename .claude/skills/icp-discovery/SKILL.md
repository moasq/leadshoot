---
id: icp-discovery
name: icp-discovery
description: Elicit or refine a user's ideal customer profile (ICP) for LeadShoot through a short, inference-first interview, then save it to the engine. Use on fresh installs (status shows no ICPs), when the user describes what they sell, when results feel off-target, or when they want to target a new area or niche.
when_to_use: Trigger phrases - "I build websites for…", "set me up", "wrong kind of leads", "let's target <city>", "add another market", first-run with empty status.
enabled: true
---
<!-- GENERATED from .agents/skills/icp-discovery/skill.md - edit there and run `python scripts/sync_agents.py`. -->

# ICP discovery - one deterministic call, then a short interview

An ICP = mode + area + categories + service/gaps + exclusions + min_score.
The niche identifier does the classification; you do the conversation.
Keep the interview under a minute.

## Step 0 - ALWAYS classify first, never guess

```bash
leadshoot niche "<the user's own words for what they sell>"
```

Deterministic: same words, same plan. The plan gives you `mode`, suggested
`categories`, weights, `say` (the explanation to give the user, in your own
voice) and `ask` (what's still missing). Three outcomes:

- **mode=gaps** - their service fixes something; proceed with the service /
  gap weights from the plan.
- **mode=fit** - they sell a product or supply (coffee, equipment, food,
  B2B services). Leads are HEALTHY BUYERS: good reviews, activity, and
  maturity rank UP; nothing gets flagged as broken. Save with `--mode fit`
  and the suggested buyer categories.
- **mode=clarify** - ask the plan's questions verbatim, then re-run
  `leadshoot niche` with the richer description. Never invent a mapping the
  identifier didn't make.

## The interview (only what the plan couldn't infer)

1. **"What do you sell?"** → feed the answer to `leadshoot niche` (step 0).
   For reference, gap services map:
   - builds/sells websites → `website_design` (no_website, broken_site, no_ssl)
   - redesigns/modernizes → `redesign` (broken_site, outdated_tech, diy_builder, …)
   - booking/ordering systems → `booking_setup` (no_booking, …)
   - reviews/reputation/local SEO → `reputation_management` (weak_reviews, few_reviews, …)
   - social media management → `social_media` (inactive_social, weak_social, …)
   - several/unsure → `general`
   Don't read this list to the user - infer from their words and confirm:
   "You build sites, so I'll target businesses whose site is missing, broken,
   or insecure - right?"
2. **"Where do you work?"** → `--area "City, Region"`. If they serve several
   cities, one ICP per city (named `<city>-<service>`).
3. **"Which business types?"** → `--categories`. Validate every category
   against `leadshoot options --json`; offer close matches for unknowns
   ("hair salon" → `salon`). If they say "any", pick the 4–6 densest
   local-service categories for their service (restaurants, salons, dentists,
   plumbers, cafes, car repair).
4. **"Skip chains and franchises?"** → default yes; only ask if their service
   plausibly targets chains.

## Save and confirm

```bash
# gap niche
leadshoot icp new --name portland-web --area "Portland, OR" \
  --categories dentist,salon,cafe --service website_design --json
# fit niche (product/supply seller)
leadshoot icp new --name pdx-coffee --area "Portland, OR" \
  --categories cafe,restaurant,bakery --mode fit --json
```

Echo back the saved profile in plain words, including which gaps will be
targeted and the min score (default 30). Offer: "Want me to run the first
find now? It'll take a minute or two."

Default qualifiers: `prefer_established` is ON - established (3y+)
businesses rank above just-started and unknown-age ones, because most users
avoid new-business risk. If the user *wants* brand-new businesses, save with
`--no-prefer-established`.

## Outside-the-niche requests: confirm, never assume

When the user asks for signals or leads their ICP doesn't target - e.g. a
`website_design` user says "check their Instagram activity" - STOP and
confirm before acting:

> "Your profile targets website gaps. Want me to (a) add social signals to
> your ICP permanently (`--gaps broken_site,no_website,inactive_social`),
> (b) do it as a one-off without changing your profile, or (c) skip it?"

Permanent expansion → re-save the ICP with a custom `--gaps` list (weights
fill in automatically). One-off → research and record signals (they're kept
and shown) but leave the ICP alone - the score only reflects targeted gaps.

## Refinement (existing ICP feels off)

- Too few leads → add categories, widen area, or lower `--min-score`.
- Wrong kind of leads → wrong `service`; re-save with the right one
  (same name overwrites; leads and pipeline are untouched).
- Ranking ignores maturity/reviews/social you researched → those gaps aren't
  in the ICP; confirm expansion as above.
- Never delete an ICP without explicit confirmation - see rule 03.
