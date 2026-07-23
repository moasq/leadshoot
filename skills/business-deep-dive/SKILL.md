---
id: business-deep-dive
name: business-deep-dive
description: Build a compact dossier on one local business before outreach - verify it's open, cross-check its web presence, socials, reviews, and positioning. Use before calling a high-priority lead, when evidence is contradictory, or when asked "tell me more about this business".
when_to_use: Trigger phrases - "tell me about <business>", "is this lead real", "prep me for the call with…", "research this one".
enabled: true
---
<!-- GENERATED from .agents/skills/business-deep-dive/skill.md - edit there and run `python scripts/sync_agents.py`. -->

# Business deep-dive - one lead, five checks, one paragraph

Goal: 5 minutes of research → a dossier the user can act on. Business-scope
facts only (rule 01): no owner home addresses, no personal socials, no
individual's data beyond their public business role.

## Start from the engine

`leadshoot show <id> --json` → everything already known: gaps, confidence,
review signals, stage history. Don't re-research what's recorded and fresh.

## The five checks (your web tools)

1. **Existence & status** - search `"<name>" <city>`. Signs of "permanently
   closed"? If closed: `leadshoot mark <id> --stage hidden --note "closed"` -
   dead leads waste the user's calls. (OSM data can lag reality.)
2. **Real web presence** - the engine checked the OSM-listed URL. Search for
   a site OSM doesn't know: `"<name>" <city> site` - a `no_website
   (unverified)` lead sometimes has a site under a different domain, or only
   a Facebook/Instagram page (which is itself a pitch angle: "your only web
   presence is a Facebook page"). Record a confirmed official URL with
   `leadshoot signal add <id> --key website.official_url --source web_search
   --text "<url>" --url "<url>" --json`.
3. **Reviews** - if not yet recorded, run the `review-research` skill.
4. **Social footprint** - business Facebook/Instagram/LinkedIn pages: active
   or abandoned? Last-post recency is a strong "cares about marketing" signal.
5. **Positioning** - what do they emphasize (price/quality/speed)? New
   ownership, renovation, "now hiring" (growth = budget)? One line.

## Persist, then present

- Aggregate review numbers → `leadshoot review add … --json`.
- Everything else → one compact note (append, don't overwrite what's there):
  `leadshoot mark <id> --note "IG active 2w ago; FB-only web presence; hiring" --json`
- Nothing to update in the engine is a valid outcome; still report it.

## Dossier format (to the user)

> **Rose City Dental** - dentist, Lake Oswego (high, broken_site verified)
> Site (rosecity.example) returns 500 since at least Jul 14. Google 4.7★
> (156) - beloved, invisible online. IG active. No booking anywhere.
> **Angle:** their reviews prove demand; a working site + booking captures it.
> **Watch out:** phone goes to front desk; owner is Dr. name-on-door.

Facts with sources, one angle, one caution. If checks contradict the engine
(site actually works, business closed), update the engine and say so - the
next agent must not rediscover it.
