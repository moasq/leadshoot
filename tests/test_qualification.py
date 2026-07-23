"""Evidence-first public qualification contract."""

from leadshoot.qualify import assess_lead, public_lead, research_jobs


def lead(**changes):
    base = {
        "id": "g1",
        "name": "Example Salon",
        "category": "salon",
        "address": "1 Main St, Boston",
        "area": "Boston",
        "phone": "+1 555 0100",
        "site_status": "working",
        "gap_flags": "",
        "confidence": "",
        "score": 88,  # private ordering implementation
        "reviews_rating": None,
        "reviews_count": None,
        "social_followers": None,
        "social_last_post_days": None,
        "social_profiles": [],
        "founded_year": None,
        "domain_registered_year": None,
    }
    return {**base, **changes}


def test_verified_major_gap_is_high_without_public_number():
    raw = lead(gap_flags="inactive_social", confidence="verified",
               social_last_post_days=300)
    result = public_lead(raw, {"mode": "gaps",
                               "gaps": ["inactive_social", "weak_social"]})
    assert result["priority"] == "high"
    assert "Verified target problem" in result["priority_reason"]
    assert "score" not in result


def test_minor_verified_gap_is_medium():
    result = assess_lead(
        lead(gap_flags="few_reviews", confidence="verified",
             reviews_rating=4.8, reviews_count=6),
        {"mode": "gaps", "gaps": ["weak_reviews", "few_reviews"]},
    )
    assert result["priority"] == "medium"


def test_unchecked_axis_is_not_sure_with_bounded_job():
    raw = lead(gap_flags="social_unchecked", confidence="unverified")
    result = assess_lead(
        raw, {"mode": "gaps", "gaps": ["inactive_social", "weak_social"]}
    )
    assert result["priority"] == "not_sure"
    assert result["research_needed"] == ["social_presence"]
    jobs = research_jobs(
        raw, {"mode": "gaps", "gaps": ["inactive_social", "weak_social"]}
    )
    assert [job["axis"] for job in jobs] == ["social_presence"]
    assert "Instagram Facebook TikTok" in jobs[0]["query"]


def test_website_research_job_names_the_persisted_signal():
    raw = lead(gap_flags="no_website", confidence="unverified")
    jobs = research_jobs(
        raw, {"mode": "gaps", "gaps": ["no_website", "broken_site"]}
    )
    assert [job["axis"] for job in jobs] == ["website_presence"]
    assert "website.official_url" in jobs[0]["record"]


def test_fit_mode_uses_healthy_buyer_evidence():
    raw = lead(gap_flags="", confidence="", site_status="working",
               reviews_rating=4.7, reviews_count=120)
    result = public_lead(raw, {"mode": "fit", "gaps": []})
    assert result["priority"] == "high"
    assert "Healthy buyer signals" in result["priority_reason"]
    assert result["research_status"] == "partial"
    assert result["context_missing"] == ["social_activity", "business_age"]
    assert "score" not in result


def test_fit_mode_sparse_candidate_stays_not_sure():
    raw = lead(gap_flags="", confidence="", site_status="no_site_listed",
               phone=None)
    result = assess_lead(raw, {"mode": "fit", "gaps": []})
    assert result["priority"] == "not_sure"
    assert result["research_needed"] == [
        "reviews", "social_activity", "business_age"
    ]
