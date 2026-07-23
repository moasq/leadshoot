"""Evidence-first lead qualification and public presentation.

The engine keeps a private numeric rank so ordering is deterministic. Users
never need to interpret that implementation detail: every public lead gets a
plain-language priority, a reason, and the smallest useful research plan.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .score import CANDIDATE_GAPS, VERIFIED

PRIORITIES = ("high", "medium", "not_sure")

_MAJOR_GAPS = {
    "broken_site",
    "no_website",
    "inactive_social",
    "weak_reviews",
    "outdated_tech",
    "no_booking",
}

_GAP_LABELS = {
    "broken_site": "broken website",
    "no_website": "no confirmed website",
    "no_ssl": "insecure website",
    "not_mobile": "non-mobile website",
    "no_booking": "no online booking",
    "weak_reviews": "weak reviews",
    "few_reviews": "thin review profile",
    "inactive_social": "inactive social account",
    "weak_social": "small social audience",
    "outdated_tech": "outdated website technology",
    "diy_builder": "DIY website",
    "slow_site": "slow website",
    "social_unchecked": "social presence not checked",
    "reviews_unchecked": "reviews not checked",
}


def _gaps(lead: dict) -> list[str]:
    raw = lead.get("gap_flags") or ""
    if isinstance(raw, str):
        return [g for g in raw.split(",") if g]
    return [str(g) for g in raw if g]


def _label(gap: str) -> str:
    return _GAP_LABELS.get(gap, gap.replace("_", " "))


def _age_years(lead: dict) -> int | None:
    year = lead.get("founded_year") or lead.get("domain_registered_year")
    if year is None:
        return None
    return max(0, datetime.now(timezone.utc).year - int(year))


def _mode(icp: dict | None, lead: dict) -> str:
    if icp:
        return str(icp.get("mode", "gaps"))
    # Old/imported records may not have a resolvable ICP. A positive private
    # rank with no gaps is the legacy shape of a fit-mode lead.
    return "fit" if not _gaps(lead) and (lead.get("score") or 0) > 0 else "gaps"


def _targeted(icp: dict | None) -> set[str]:
    if not icp:
        return set()
    return set(icp.get("gaps") or (icp.get("weights") or {}).keys())


def _evidence(lead: dict, mode: str) -> list[str]:
    items: list[str] = []
    gaps = [g for g in _gaps(lead) if g not in CANDIDATE_GAPS]
    if gaps:
        prefix = "Verified" if lead.get("confidence") == VERIFIED else "Possible"
        items.append(f"{prefix}: {', '.join(_label(g) for g in gaps)}")
    if mode == "fit" and lead.get("site_status") in {
        "working", "no_ssl", "protected"
    }:
        items.append("Operating website")
    elif lead.get("official_website"):
        items.append("Official website found; live check pending")
    rating, count = lead.get("reviews_rating"), lead.get("reviews_count")
    if rating is not None:
        items.append(f"Reviews: {float(rating):.1f}★ from {int(count or 0)}")
    last_post = lead.get("social_last_post_days")
    if last_post is not None:
        items.append(f"Latest social activity: {int(last_post)} days ago")
    followers = lead.get("social_followers")
    if followers is not None:
        items.append(f"Social audience: {int(followers):,}")
    age = _age_years(lead)
    if age is not None:
        items.append(f"Established at least {age} years")
    if lead.get("phone"):
        items.append("Phone on file")
    return items


def assess_lead(lead: dict, icp: dict | None = None) -> dict:
    """Return the qualitative decision and efficient research context."""
    mode = _mode(icp, lead)
    gaps = _gaps(lead)
    real_gaps = [g for g in gaps if g not in CANDIDATE_GAPS]
    targeted = _targeted(icp)
    weights = (icp or {}).get("weights") or {}
    required: list[str] = []
    context: list[str] = []

    if mode == "fit":
        positives: list[str] = []
        if lead.get("site_status") in {"working", "no_ssl", "protected"}:
            positives.append("an operating website")
        rating, count = lead.get("reviews_rating"), lead.get("reviews_count")
        if rating is not None and count is not None \
                and float(rating) >= 4.0 and int(count) >= 10:
            positives.append("a healthy review profile")
        if lead.get("social_last_post_days") is not None \
                and int(lead["social_last_post_days"]) <= 60:
            positives.append("recent social activity")
        age = _age_years(lead)
        if age is not None and age >= 3:
            positives.append("an established operating history")

        if len(positives) >= 2:
            priority = "high"
            reason = "Healthy buyer signals: " + " and ".join(positives[:3]) + "."
        elif positives:
            priority = "medium"
            reason = f"Potential buyer with {positives[0]}, but fit is only partly qualified."
        else:
            priority = "not_sure"
            reason = "The business matches the buyer type, but there is not enough evidence of buying readiness."

        missing_fit = []
        if lead.get("reviews_count") is None:
            missing_fit.append("reviews")
        if lead.get("social_last_post_days") is None:
            missing_fit.append("social_activity")
        if _age_years(lead) is None:
            missing_fit.append("business_age")
        if priority == "high":
            context.extend(missing_fit)
        else:
            required.extend(missing_fit)
    else:
        if real_gaps and lead.get("confidence") == VERIFIED:
            high_impact = any(
                float(weights.get(g, 1.0 if g in _MAJOR_GAPS else 0.0)) >= 0.7
                for g in real_gaps
            )
            if high_impact or len(real_gaps) >= 2:
                priority = "high"
                reason = "Verified target problem: " + ", ".join(
                    _label(g) for g in real_gaps[:3]
                ) + "."
            else:
                priority = "medium"
                reason = "Verified improvement opportunity: " + ", ".join(
                    _label(g) for g in real_gaps[:3]
                ) + "."
        elif real_gaps:
            priority = "not_sure"
            reason = "A possible target problem was found, but it has not been confirmed."
        elif any(g in CANDIDATE_GAPS for g in gaps):
            priority = "not_sure"
            reason = "This is a candidate business; the offer-specific signal has not been checked."
        else:
            priority = "not_sure"
            reason = "No target problem has been confirmed."

        if "social_unchecked" in gaps:
            required.append("social_presence")
        if "reviews_unchecked" in gaps:
            required.append("reviews")
        if "no_website" in real_gaps and lead.get("confidence") != VERIFIED:
            required.append("website_presence")

        # Reviews and age make outreach context stronger, but are not required
        # to decide a website/social/booking gap unless explicitly targeted.
        if lead.get("reviews_count") is None and not (
                {"weak_reviews", "few_reviews"} & targeted):
            context.append("reviews")
        if _age_years(lead) is None:
            context.append("business_age")

    required = list(dict.fromkeys(required))
    context = [x for x in dict.fromkeys(context) if x not in required]
    if required:
        research_status = "needs_research"
    elif priority in {"high", "medium"}:
        research_status = "partial" if context else "ready"
    else:
        research_status = "no_match"

    if required:
        next_action = "Quick-check " + ", ".join(
            x.replace("_", " ") for x in required
        ) + " before outreach."
    elif priority == "high":
        next_action = "Ready for personalized outreach."
    elif priority == "medium":
        next_action = "Review the evidence, then personalize outreach."
    else:
        next_action = "Do not pitch yet; skip unless new evidence appears."

    return {
        "priority": priority,
        "priority_reason": reason,
        "research_status": research_status,
        "research_needed": required,
        "context_missing": context,
        "evidence": _evidence(lead, mode),
        "next_action": next_action,
    }


def public_lead(lead: dict, icp: dict | None = None) -> dict:
    """Public lead shape: qualitative context, never the private rank."""
    out = dict(lead)
    out.pop("score", None)
    out.update(assess_lead(lead, icp))
    return out


def research_jobs(lead: dict, icp: dict | None = None,
                  include_context: bool = False) -> list[dict]:
    """Small, independent checks an agent can run concurrently."""
    assessment = assess_lead(lead, icp)
    axes = list(assessment["research_needed"])
    if include_context:
        axes += assessment["context_missing"]
    axes = list(dict.fromkeys(axes))
    name = lead.get("name") or ""
    location = lead.get("address") or lead.get("area") or ""
    subject = " ".join(f'"{x}"' for x in (name, location) if x)
    profiles = lead.get("social_profiles") or []
    jobs = []
    for axis in axes:
        if axis == "website_presence":
            jobs.append({
                "axis": axis,
                "query": f"{subject} official website".strip(),
                "record": "If identity matches, record it with signal key website.official_url; otherwise leave unknown.",
            })
        elif axis in {"social_presence", "social_activity"}:
            jobs.append({
                "axis": axis,
                "query": f"{subject} Instagram Facebook TikTok".strip(),
                "known_profiles": profiles,
                "record": "Record follower count and days since the latest business post; keep unknown if identity is ambiguous.",
            })
        elif axis == "reviews":
            jobs.append({
                "axis": axis,
                "query": f"{subject} reviews".strip(),
                "record": "Record aggregate rating and review count from a verified business profile.",
            })
        elif axis == "business_age":
            jobs.append({
                "axis": axis,
                "query": f"{subject} founded established about".strip(),
                "record": "Record a founding year only from the official site or a credible registry.",
            })
    return jobs
