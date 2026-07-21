---
id: business-signals
name: business-signals
description: Research qualifier signals for LeadShoot leads - when the business started (established vs just-opened) and its social media health (followers, last post, activity) - using your own web tools, then persist them so scoring can favor established businesses and flag dormant social presence. Use when qualifying leads before outreach, when the user sells social media management, when they ask "how old is this business" or "are they active on Instagram", or when ranking feels blind to business maturity.
when_to_use: Trigger phrases - "are they established", "when did they open", "check their socials", "last time they posted", "followers", "qualify by age", "avoid new businesses".
enabled: true
---

# Business signals - maturity and social health

**Why maturity matters:** users fear just-opened businesses (they churn, they
haggle, they vanish). LeadShoot encodes that as a *qualifier*, not a gap:
established (3y+) leads get a boost, just-started (<1y) a real penalty,
**unknown age is kept but discounted** - never dropped. Your research turns
"unknown" into a fair rank.

**Division of labor (rule 01):** you research public pages with your own web
tools; the engine stores aggregates only. Business facts, never personal data.

## Persist with `leadshoot signal add`

```bash
leadshoot signal add <id> --key business.founded_year --source website \
  --value 2009 --url "https://…/about" --json
leadshoot signal add <id> --key social.followers --source instagram --value 1240 --json
leadshoot signal add <id> --key social.last_post_days --source instagram --value 8 --json
```

Scored keys: `business.founded_year`, `social.followers`,
`social.last_post_days` (plus `reviews.*` - see the `review-research` skill).
Any other key is stored for the future but not scored. The lead rescored on
every add.

## Automate the floor first: `leadshoot enrich`

Before hand-researching ages, run `leadshoot enrich --icp X --json` - it dates
leads automatically via RDAP domain-registration lookups (open protocol).
Domain age is a *lower bound* on business age; the maturity qualifier uses
it whenever `business.founded_year` is absent. Hand-research (below) then
only for high-value leads where the true founding year strengthens the
pitch ("34 years in business…").

## Finding the founding year (best → weakest evidence)

1. **Their own site**: About page "since 1998", footer "est. 2011",
   copyright range start.
2. **Business registries**: OpenCorporates, national commercial registers
   (e.g. Oman CR via the Ministry of Commerce portal) - incorporation date.
3. **LinkedIn company page**: "Founded" field.
4. **Facebook page transparency**: page creation date (lower bound).
5. **Oldest Google/TripAdvisor review date** (lower bound - "at least since").
6. **Domain WHOIS creation date** (weak lower bound; domains change hands).

Record the YEAR with the source you used. Lower-bound evidence is fine -
note it ("oldest review 2016 → founded ≤2016"). Conflicting evidence: record
per source; the engine takes the earliest.

## Social health (per platform: instagram, facebook, tiktok)

From the public profile only: **followers** (count) and **last post** (days
ago). Thresholds the engine applies: no post in >90 days → `inactive_social`
gap; <500 followers → `weak_social` gap. No profile found at all? Record
`--key social.followers --value 0 --source instagram --note "no profile
found"` - for a social-media ICP, *absence of presence is the pitch*.

Identity check before recording (same as reviews): name AND city/street/phone
must match. Linked-from-their-website profiles are the gold standard.

## Interpreting for the user

- **Established + verified gap** = the dream lead: proven business, real
  problem, low risk. Say it that way.
- **Just-started** leads rank low by design; if the user *wants* new
  businesses (some do - first-website deals), set the ICP with
  `--no-prefer-established` after confirming.
- **Inactive social + established** = classic social-media-management lead:
  "12 years in business, silent on Instagram for 8 months."
- Signals older than ~90 days are stale for social; re-check before a pitch.

## Scope guard (rule: confirm outside the niche)

If the user's ICP doesn't target social gaps (service is website_design,
say) and they ask for social qualification, confirm before expanding:
"Your profile targets website gaps - want me to add social signals to it
(--gaps), or keep this a one-off?" Never silently widen an ICP.
