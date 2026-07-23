---
id: quick-qualification
name: quick-qualification
description: Turn a newly discovered LeadShoot roster into decision-ready leads by running the bounded research queue, persisting verified business signals, and reporting high/medium/not_sure outcomes. Use after find/import-gmaps, when many leads are not_sure, when the user wants efficient context, or for fit-mode product buyers that need readiness qualification.
when_to_use: Trigger phrases - "qualify these leads", "research them quickly", "give me context", "which are worth calling", "run the funnel", after a find response contains research_queue jobs.
enabled: true
---

# Quick qualification - research only what changes the decision

The funnel is:

```text
Google Maps discovery (when explicitly selected)
  → concurrent website checks
  → high / medium / not_sure
  → bounded research queue
  → persist facts
  → final call list
```

Start with the queue, never a free-form deep dive:

```bash
leadshoot research-queue --search latest --json
```

Each queue item contains independent jobs on one or more axes:
`website_presence`, `social_presence` / `social_activity`, `reviews`, and
`business_age`. Run separate leads in parallel when the host supports
sub-agents. Keep one lead's identity checks together so same-name businesses
cannot be mixed.

## Efficient evidence pass

1. Verify identity using business name plus street or phone.
2. Use any `known_profiles` first; these were linked by the official site.
3. Search only the axes listed in the job. Do not research every possible
   fact merely because it exists.
4. Persist business-level facts:
   - reviews → `leadshoot review add`
   - followers / last post → `leadshoot signal add`
   - founded year → `leadshoot signal add`
   - corrected official website → `leadshoot signal add <id> --key
     website.official_url --source web_search --text "<url>" --url "<url>"
     --json`
5. Re-read with `leadshoot leads --search latest --json`. Every recorded
   signal reclassifies immediately.

Unknown is a valid result. If identity is ambiguous or a source cannot be
verified, record nothing and leave the lead `not_sure`.

## Decision meaning

- `high`: strong verified target problem, or at least two healthy-buyer
  signals in fit mode. Ready for personalized outreach.
- `medium`: real but smaller opportunity, or only partly qualified buyer.
  Review the evidence; a quick extra check may upgrade it.
- `not_sure`: decisive evidence is missing or inferred only. Do not pitch it
  as fact. Work the research queue or skip it.

Report the final set as `priority · name · reason · evidence · next_action`.
Never expose or invent a numeric score.
