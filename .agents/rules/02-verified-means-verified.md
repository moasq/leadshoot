# Rule 2 - Verified means verified

LeadShoot's core promise is that a flagged gap is real. Never weaken the ladder:

- `confidence: verified` - the engine fetched the site and observed the
  problem (HTTP error, dead domain, no TLS), or a review signal with a
  recorded source says so.
- `confidence: unverified` - inferred, not observed: a missing OSM website
  tag (measured only ~44% precise) or a host that resolves but doesn't answer
  (may be bot defense). Unverified scores are discounted and must be
  *presented* as unconfirmed: say "likely has no website (unconfirmed)",
  never "has no website".
- WAF/bot-defense responses (401/403/405/406/429) mean the site is **alive**
  (`protected`) - never call it broken, never pitch a fix for it.
- robots.txt disallow means we don't look (`blocked`) - we don't judge what
  we were asked not to fetch.
- Review gaps require data: no recorded signals means *unknown*, and unknown
  is never a gap. `weak_reviews` needs ≥5 reviews before a low rating counts.
- Before telling a user "this business's site is broken", prefer confirming
  with a fresh `leadshoot recheck` if the check is older than ~30 days.
