---
id: outreach-prep
name: outreach-prep
description: Turn a qualified LeadShoot lead into an outreach brief grounded in verified evidence. Use when the user is ready to contact high/medium leads, asks "what do I say to…", or wants a prepared call list.
when_to_use: Trigger phrases - "what do I say", "draft an email to", "prep my calls", "pitch for <business>", "make me a call list".
enabled: true
---
<!-- GENERATED from .agents/skills/outreach-prep/skill.md - edit there and run `python scripts/sync_agents.py`. -->

# Outreach prep - the gap IS the pitch

LeadShoot's edge is that every lead carries a *specific, verified reason* to
reach out. The brief's job is to say that reason plainly and connect it to
one outcome the business cares about. Rule 04 binds everything here.

## Inputs

`leadshoot show <id> --json` - use `gap_flags`, `confidence`,
`priority`, `priority_reason`, `evidence`, `reviews_rating/count`, category,
and the user's `note` history. `not_sure` is not outreach-ready: run
`quick-qualification` first. If reviews
are unknown and the lead is high-value, suggest `review-research` first -
a rating transforms the opener.

## Honesty calibration (non-negotiable)

- `verified` gap → assert it: "your site's been returning an error".
- `unverified` → invite correction: "I couldn't find a website for you -
  did I miss it?" Never assert an unverified gap.
- Never manufacture urgency ("customers are fleeing!"), never disparage,
  never claim you can remove bad reviews.

## Angle by gap (+ reviews)

| Situation | Opener angle |
|---|---|
| ≥4.5★ + broken/no site | Lead with THEIR rating: "156 people gave you 4.7 stars - but when they search, there's nothing to click." |
| broken_site (verified) | "Your website's down - you may not know. That's lost calls every day it 500s." |
| no_website (unverified) | "Couldn't find a site for you - if there isn't one, here's what one would do for a <category> in <city>." |
| no_ssl / not_mobile | "Your site works, but browsers flag it / half your visitors are on phones and it doesn't fit." |
| weak_reviews | "You're at 3.1★. Here's a system to earn and respond to reviews." (earning, never gaming) |
| few_reviews | "12 reviews means you're invisible in map results - even though you're good." |
| no_booking | "People decide at 9pm. A booking button captures them; your phone doesn't." |

## Formats

**Call brief** (phone-first is the norm for local): 3 lines - who + verified
hook + one question. Plus a 15-second voicemail variant.

**Email** (only if the user has an address legitimately): subject that names
the gap, honestly; 4 sentences max; one CTA; MUST include the user's real
name, business name, and physical postal address, and an opt-out line -
CAN-SPAM applies to all commercial email, no B2B exemption. Refuse volume
blasting; sequences and automation are out of scope by design.

## Batch: "prep my day"

1. `leadshoot leads --stage new --priority high --json` (then medium if the
   user wants a longer list).
2. Brief per lead, grouped: 🔥 loved-but-invisible first, then verified
   breaks, then unverified maybes.
3. After the user acts: `leadshoot mark <id> --stage contacted --note "<what
   happened>" --json` - always offer to record outcomes; the pipeline is the
   memory.
