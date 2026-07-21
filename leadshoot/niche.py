"""Deterministic niche identifier.

Takes the user's own words for what they sell and returns a targeting PLAN:
which mode applies (gap-hunting vs fit-based buyer search), which gaps or
qualifiers matter, which business categories to look in, what to tell the
user, and what still has to be asked. Rule-based and ordered - the same
description always yields the same plan, so conversational agents wrap it
instead of guessing. "No website" is one rule in this table, not the product.

Modes:
  gaps    - the lead is a business with a fixable problem the service solves
  fit     - the lead is a healthy buyer of a product/supply (nothing broken:
            good reviews, activity, and maturity RAISE the score)
  clarify - the description doesn't identify targeting yet; ask the listed
            questions and re-run
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .icp import GAP_WEIGHTS, SERVICES


@dataclass
class NichePlan:
    mode: str                          # gaps | fit | clarify
    matched_rule: str                  # which rule fired (determinism audit)
    service: str | None = None         # for gaps mode
    gaps: dict[str, float] = field(default_factory=dict)
    categories: list[str] = field(default_factory=list)  # suggested buyers
    say: str = ""                      # what to tell the user
    ask: list[str] = field(default_factory=list)         # still needed

    def to_dict(self) -> dict:
        return {
            "mode": self.mode, "matched_rule": self.matched_rule,
            "service": self.service, "gaps": self.gaps,
            "categories": self.categories, "say": self.say, "ask": self.ask,
        }


_ASK_AREA = 'Where do you work? (city/neighborhood, e.g. "Astoria, Queens")'
_ASK_CATS = "Which business types should I include? (suggested list attached)"

_HOSPITALITY = ["restaurant", "cafe", "bar", "bakery", "hotel"]
_MAIN_STREET = ["restaurant", "cafe", "salon", "bar", "bakery", "gym",
                "car_repair", "dentist", "florist", "pet"]

# ordered, first match wins; keywords are lowercase substring matches
_RULES: list[tuple[str, tuple[str, ...], dict]] = [
    ("websites", ("website", "web design", "landing page", "web dev",
                  "build sites", "webflow"),
     dict(mode="gaps", service="website_design",
          say="You fix missing/broken web presence, so leads are businesses "
              "whose site is absent, dead, or insecure - verified live.")),
    ("redesign", ("redesign", "rebuild", "modernize", "revamp", "refresh"),
     dict(mode="gaps", service="redesign",
          say="You upgrade existing sites, so leads run outdated platforms, "
              "DIY templates, or slow/non-mobile sites - detected on every "
              "homepage.")),
    ("social-media", ("social media", "instagram", "tiktok", "content "
                      "creation", "community management", "social account"),
     dict(mode="gaps", service="social_media",
          say="You manage social presence, so leads have dormant or tiny "
              "accounts. I'll need social signals recorded (I can research "
              "them) before these gaps score.")),
    ("booking-software", ("booking", "reservation", "scheduling",
                          "appointment", "online ordering", "ordering system",
                          "pos", "point of sale"),
     dict(mode="gaps", service="booking_setup",
          say="You sell booking/ordering capability, so leads are busy "
              "categories with no way to book or order online.")),
    ("reputation", ("reputation", "review management", "reviews", "ratings",
                    "local seo", "seo", "google ranking"),
     dict(mode="gaps", service="reputation_management",
          say="You improve how businesses look online, so leads have weak "
              "or thin review profiles. Review signals score after research "
              "or a gmaps import. Note: LeadShoot has no Google-ranking data; "
              "review strength is the honest proxy it can verify.")),
    ("design-branding", ("brand", "logo", "graphic design", "identity",
                         "design service", "visual"),
     dict(mode="gaps", service=None,
          gaps={"diy_builder": 0.8, "no_website": 0.7, "outdated_tech": 0.6,
                "weak_social": 0.5},
          say="You sell design, so leads look template-built, absent, or "
              "visually dated - DIY builders and outdated platforms are "
              "your opening.")),
    ("coffee-supply", ("coffee", "beans", "roaster", "roastery", "espresso"),
     dict(mode="fit", categories=["cafe", "restaurant", "bakery", "hotel"],
          say="You sell a product, not a fix - so leads are HEALTHY buyers: "
              "established cafés and restaurants with good reviews and real "
              "activity rank highest. Nothing needs to be broken.")),
    ("food-supply", ("food suppl", "produce", "meat", "seafood", "beverage",
                     "ingredients", "wholesale", "distributor", "drinks"),
     dict(mode="fit", categories=_HOSPITALITY,
          say="Product niche: leads are thriving hospitality businesses "
              "likely to buy - ranked by reviews, activity, and maturity.")),
    ("equipment-supply", ("furniture", "equipment", "kitchen", "appliance",
                          "fixture", "machines"),
     dict(mode="fit", categories=_HOSPITALITY + ["salon"],
          say="Product niche: leads are established venues that buy "
              "equipment - health and maturity rank them, not problems.")),
    ("supplies", ("packaging", "supplies", "cleaning product", "detergent",
                  "consumables", "uniforms"),
     dict(mode="fit", categories=_MAIN_STREET,
          say="Recurring-supply niche: steady, established main-street "
              "businesses rank highest.")),
    ("b2b-services", ("insurance", "payroll", "accounting service",
                      "bookkeeping", "legal service", "hr "),
     dict(mode="fit", categories=_MAIN_STREET,
          say="Professional-services niche: any established local business "
              "is a potential client - maturity and health do the ranking.")),
    ("generic-software", ("software", "saas", "app", "platform", "crm",
                          "system for"),
     dict(mode="clarify",
          say="Software could be a gap niche (it replaces something missing, "
              "like booking) or a fit niche (any healthy business buys it).",
          ask=["What problem does your software solve for the business?",
               "Which kinds of businesses use it today?"])),
]

_CLARIFY = dict(
    mode="clarify",
    say="I couldn't map that to a targeting plan deterministically.",
    ask=["What problem does it solve for a local business - or is it a "
         "product they'd buy when healthy?",
         "Who buys it today? (business types)",
         "Is the buying signal something visible online (site, socials, "
         "reviews, booking) or just being the right kind of business?"],
)


def identify(description: str) -> NichePlan:
    """Deterministically classify a seller description into a plan."""
    text = " " + (description or "").strip().lower() + " "
    for name, keywords, spec in _RULES:
        if any(k in text for k in keywords):
            plan = NichePlan(mode=spec["mode"], matched_rule=name,
                             service=spec.get("service"),
                             gaps=dict(spec.get("gaps", {})),
                             categories=list(spec.get("categories", [])),
                             say=spec["say"],
                             ask=list(spec.get("ask", [])))
            if plan.mode == "gaps":
                if plan.service and not plan.gaps:
                    plan.gaps = dict(SERVICES[plan.service])
                plan.ask = [_ASK_AREA, _ASK_CATS,
                            "Skip chains and franchises? (default yes)"]
            elif plan.mode == "fit":
                plan.ask = [_ASK_AREA,
                            "Any buyer types to add or drop from the "
                            "suggestions?"]
            return plan
    return NichePlan(matched_rule="none", **_CLARIFY)
