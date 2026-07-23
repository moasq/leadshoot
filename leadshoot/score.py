"""Opportunity scoring.

Deterministic and explainable: the dominant gap sets the base (its ICP weight
x 100), each additional gap adds a small bonus, a listed phone adds a small
actionability bonus. Capped at 100.
"""

from __future__ import annotations

from .check import (BLOCKED, BROKEN, DIY_BUILDERS, NO_SITE, NO_SSL, PROTECTED,
                    UNREACHABLE, WORKING, CheckResult)

EXTRA_GAP_BONUS = 8
PHONE_BONUS = 5

VERIFIED = "verified"
UNVERIFIED = "unverified"

# Offer-framed candidate placeholders. When an offer's HEADLINE gap is a
# researched-signal gap (social or reviews) and that signal hasn't been
# gathered yet, the lead surfaces as a candidate framed around the offer -
# "not audited yet, go look" - instead of falling back to website framing.
# Synthetic (never OSM/live-check facts, never user-selectable), always
# unverified, and replaced by the real signal gap the moment it's recorded.
SOCIAL_SIGNAL_GAPS = ("inactive_social", "weak_social")
REVIEW_SIGNAL_GAPS = ("weak_reviews", "few_reviews")
CANDIDATE_GAPS = ("social_unchecked", "reviews_unchecked")
UNCHECKED_WEIGHTS = {"social_unchecked": 0.5, "reviews_unchecked": 0.5}


def gaps_from_check(result: CheckResult, has_website_tag: bool,
                    wanted_gaps: list[str]) -> tuple[list[str], str]:
    """Translate a check result into (gap_flags, confidence)."""
    gaps: list[str] = []
    confidence = VERIFIED

    def site_quality_gaps() -> list[str]:
        out = []
        if result.is_mobile == 0:
            out.append("not_mobile")
        if result.has_booking == 0:
            out.append("no_booking")
        if result.outdated:
            out.append("outdated_tech")
        if result.builder in DIY_BUILDERS:
            out.append("diy_builder")
        if result.slow:
            out.append("slow_site")
        return out

    if not has_website_tag:
        # OSM has no website tag: a real signal, but tags are incomplete -
        # never presented as verified (measured ~44% naive precision).
        return (["no_website"] if "no_website" in wanted_gaps else [], UNVERIFIED)

    if result.status == BROKEN:
        gaps.append("broken_site")
    elif result.status == UNREACHABLE:
        # DNS resolves but nothing answers: flagged, but honestly downgraded -
        # it may be a bot block our client can't see past.
        gaps.append("broken_site")
        confidence = UNVERIFIED
    elif result.status == NO_SSL:
        gaps.append("no_ssl")
        gaps.extend(site_quality_gaps())
    elif result.status == WORKING:
        gaps.extend(site_quality_gaps())
    elif result.status in (BLOCKED, PROTECTED):
        # robots.txt told us not to look, or a WAF answered (site is alive
        # behind bot defense). Either way we don't guess.
        return [], VERIFIED

    gaps = [g for g in gaps if g in wanted_gaps]
    return gaps, confidence


WEAK_RATING_BELOW = 3.5
WEAK_RATING_MIN_COUNT = 5
FEW_REVIEWS_BELOW = 15

INACTIVE_SOCIAL_DAYS = 90     # no post in ~3 months = dormant presence
WEAK_SOCIAL_FOLLOWERS = 500

# maturity is a QUALIFIER, not a gap: users prefer established businesses
# (less risk), so age scales the score. Unknown keeps the lead, discounted -
# "not enough info" never disqualifies, it just ranks lower than proven.
ESTABLISHED_YEARS = 3
MATURITY_FACTORS = {
    "established": 1.08,   # 3+ years: proven, slight boost
    "growing": 0.95,       # 1-3 years
    "just_started": 0.70,  # <1 year: users avoid the risk
    "unknown": 0.85,       # kept, but below anything proven
}


def maturity(founded_year: int | None,
             prefer_established: bool = True) -> tuple[str, float]:
    """(label, score factor) from founding evidence."""
    import datetime

    if founded_year is None:
        label = "unknown"
    else:
        age = datetime.date.today().year - int(founded_year)
        label = ("established" if age >= ESTABLISHED_YEARS
                 else "growing" if age >= 1 else "just_started")
    factor = MATURITY_FACTORS[label] if prefer_established else 1.0
    return label, factor


def social_gaps(followers: int | None, last_post_days: int | None,
                wanted_gaps: list[str]) -> list[str]:
    """Gaps from recorded social signals. No data => unknown => no gap."""
    gaps: list[str] = []
    if last_post_days is not None and last_post_days > INACTIVE_SOCIAL_DAYS:
        gaps.append("inactive_social")
    if followers is not None and followers < WEAK_SOCIAL_FOLLOWERS:
        gaps.append("weak_social")
    return [g for g in gaps if g in wanted_gaps]


def candidate_gaps(weights: dict[str, float], summary: dict) -> list[str]:
    """The offer's 'not audited yet' placeholder, if any.

    Only the offer's headline axis (its top-weighted gap) produces a
    placeholder, and only while no signal on that axis is recorded - so a
    social seller sees 'social not audited', a reputation seller 'reviews
    not audited', and a website seller sees neither. Researching the signal
    replaces the placeholder with the real gap, or clears it if healthy.
    This is what keeps a signal-driven pipeline framed by the offer instead
    of collapsing to 'no website' before any research is done.
    """
    if not weights:
        return []
    top = max(weights, key=lambda g: weights[g])
    if top in SOCIAL_SIGNAL_GAPS:
        if summary["social_followers"] is None \
                and summary["social_last_post_days"] is None:
            return ["social_unchecked"]
    elif top in REVIEW_SIGNAL_GAPS:
        if summary["reviews_count"] is None:
            return ["reviews_unchecked"]
    return []


def review_gaps(rating: float | None, count: int | None,
                wanted_gaps: list[str]) -> list[str]:
    """Gaps derived from agent-recorded review signals.

    No signals recorded => no gaps (unknown is not a gap). weak_reviews needs
    a minimum sample so one angry review doesn't condemn a business.
    """
    if count is None:
        return []
    gaps: list[str] = []
    if rating is not None and count >= WEAK_RATING_MIN_COUNT \
            and rating < WEAK_RATING_BELOW:
        gaps.append("weak_reviews")
    if count < FEW_REVIEWS_BELOW:
        gaps.append("few_reviews")
    return [g for g in gaps if g in wanted_gaps]


def score(gaps: list[str], weights: dict[str, float],
          has_phone: bool = False, confidence: str = VERIFIED,
          maturity_factor: float = 1.0) -> int:
    if not gaps:
        return 0
    present = [weights.get(g, UNCHECKED_WEIGHTS.get(g, 0.0)) for g in gaps]
    base = 100 * max(present)
    bonus = EXTRA_GAP_BONUS * max(0, len([p for p in present if p > 0]) - 1)
    total = base + bonus + (PHONE_BONUS if has_phone else 0)
    if confidence == UNVERIFIED:
        total *= 0.75  # unverified signals rank below verified ones
    total *= maturity_factor
    return min(100, round(total))


def status_for_no_tag() -> str:
    return NO_SITE


def fit_score(site_status: str | None, rating: float | None,
              review_count: int | None, followers: int | None,
              last_post_days: int | None, has_phone: bool,
              maturity_factor: float) -> int:
    """Rank a HEALTHY BUYER for fit-mode niches (products, supplies,
    professional services). The polarity is inverted vs gap mode: good
    reviews, activity, reachability and maturity all raise the score,
    and nothing is flagged as broken. Deterministic and explainable:

        base 55
        + working website        +10   (real, reachable operation)
        + strong reviews         +20 / +12 (4.5★×25+ / 4.0★×10+)
        - struggling reviews     -15   (<3.0★ over 10+: risky customer)
        + active social (≤30d)   +8
        + audience ≥5000         +5
        + phone on file          +5
        × maturity factor              (established buyers stay in business)
    """
    total = 55.0
    if site_status in (WORKING, NO_SSL, PROTECTED):
        total += 10
    if rating is not None and review_count:
        if rating >= 4.5 and review_count >= 25:
            total += 20
        elif rating >= 4.0 and review_count >= 10:
            total += 12
        elif rating < 3.0 and review_count >= 10:
            total -= 15
    if last_post_days is not None and last_post_days <= 30:
        total += 8
    if followers is not None and followers >= 5000:
        total += 5
    if has_phone:
        total += 5
    total *= maturity_factor
    return max(5, min(100, round(total)))
