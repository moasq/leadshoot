# Rule 1 - Data ethics: business facts only, clean sources only

- The **default provider** touches only open data: OpenStreetMap (bulk via
  Geofabrik extracts; small ad-hoc Overpass queries with politeness), the
  business's own website (homepage fetch, robots.txt honored), and CC0
  sources like Wikidata. The engine itself never scrapes Google Maps, Yelp,
  or any ToS-protected platform.
- The **gmaps provider is opt-in and user-supplied**: the user runs
  gosom/google-maps-scraper themselves (or imports its results file).
  Scraping Google Maps violates Google's ToS - it is the user's explicit,
  informed choice, never a default, and never something an agent switches on
  silently. When a user asks for it, state the tradeoff once, plainly.
  From imported gmaps data we accept identity fields and review AGGREGATES;
  we refuse the harvested `emails` field (the no-email-harvesting line
  applies to every provider).
- **Agents** may research public review pages and business profiles using
  their own web tools, subject to each site's terms. What comes back into
  LeadShoot is **aggregates only**: source name, star rating, review count,
  profile URL, a short note. Never store review text dumps, reviewer names,
  or any personal data.
- Never harvest, guess, or pattern-generate email addresses. Owner-published
  business contacts (OSM `phone`, `contact:email`) are the ceiling.
- If a record looks like a sole trader (personal name as business name,
  personal email), treat contact details as personal data under GDPR/CCPA:
  flag it in a note, don't enrich it further.
- OSM-derived output always carries: "Data © OpenStreetMap contributors
  (ODbL)".
