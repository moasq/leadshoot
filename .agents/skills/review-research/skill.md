---
id: review-research
name: review-research
description: Research a lead's online reviews (Google Maps rating plus the niche's review sites - Yelp for restaurants, Healthgrades for doctors, Avvo for lawyers, Angi for trades) using your own web search/fetch tools, then persist the aggregates into LeadShoot so weak_reviews/few_reviews gaps get scored. Use when reviews matter to the pitch, when the user sells reputation management, when qualifying hot leads before outreach, or when asked "what are this business's reviews like?".
when_to_use: Trigger phrases - "check their reviews", "how are they rated", "qualify these leads", "reputation leads", after find when the ICP service is reputation_management.
enabled: true
---

# Review research - agent researches, engine remembers

**Division of labor (rule 01):** the LeadShoot engine never scrapes review
platforms. YOU research public profile pages with your own web tools, then
persist ONLY aggregates: source, star rating, review count, profile URL,
a one-line note. Never store review text dumps or reviewer names/identities.

## Procedure (per lead)

1. `leadshoot show <id> --json` → name, category, address, phone. Skip leads
   whose signals are fresh (review_signals `added_at` < ~60 days).
2. Web-search the business: `"<name>" <city> reviews` and
   `"<name>" <street>` (the street disambiguates same-name businesses).
   The search snippets usually surface Google's aggregate (e.g. "4.6 ★ (213)")
   without opening Maps.
3. Check the niche's sources (below). 2–3 sources max - Google plus the
   niche's dominant one is usually enough signal.
4. **Verify identity before recording**: name AND (street or phone) must
   match. Same-name businesses in one city are common; a wrong match poisons
   the lead. If unsure, record nothing and note the ambiguity.
5. Persist each source:
   ```bash
   leadshoot review add <id> --source google --rating 4.6 --count 213 \
     --url "<profile url>" --json
   leadshoot review add <id> --source yelp --rating 3.9 --count 87 --json
   ```
   The lead rescored immediately: rating < 3.5 (over ≥5 reviews) →
   `weak_reviews`; total < 15 → `few_reviews`. No signals → unknown, no gap.

## Niche → review sources

| Category | Check first | Also worth checking |
|---|---|---|
| restaurant, cafe, bar, bakery | Google, **Yelp** | TripAdvisor, OpenTable |
| dentist, doctor | Google, **Healthgrades** | Zocdoc, Vitals, Yelp |
| vet | Google, Yelp | - |
| salon, barber, tattoo | Google, **Yelp** | Booksy, StyleSeat |
| plumber, electrician, roofer, carpenter, painter | Google, **Angi** | HomeAdvisor, Houzz, Thumbtack, BBB |
| car_repair, car_dealer | Google, Yelp | RepairPal, DealerRater, CarGurus |
| lawyer | Google, **Avvo** | Justia, Martindale, Yelp |
| accountant, insurance | Google, Yelp | BBB |
| real_estate | Google, **Zillow** | Realtor.com |
| hotel | Google, **TripAdvisor** | Booking.com, Expedia |
| gym | Google, Yelp | ClassPass |
| photographer, florist, jewelry | Google, Yelp | The Knot, WeddingWire |
| pharmacy, optician, laundry, other | Google | Yelp |

Respect each site's terms - read public pages, don't automate bulk
extraction of them, and prefer search-snippet aggregates when available.

## Interpreting what you find (say this to the user)

- **< 3.5★ with volume** → reputation-management lead: they're losing
  customers at the decision moment.
- **< 15 reviews total** → review-generation lead: invisible in local
  rankings regardless of quality.
- **≥ 4.5★ but broken/no website** → the HOTTEST web lead: a beloved
  business that's invisible online. Lead the pitch with their own rating.
- **Great reviews + great site** → not a lead; mark it hidden if it keeps
  surfacing.
- Found nothing at all? That is itself a `few_reviews`-grade insight - record
  `--count 0 --note "no findable profiles"` so it scores and isn't
  re-researched.

## Batch mode

For "qualify my top N": iterate `leadshoot leads --min-score 50 --json`,
research each, persist, then re-rank with `leadshoot leads --json` and present
movers. Consider delegating per-lead research to the `review-analyst`
sub-agent to keep the main conversation clean.
