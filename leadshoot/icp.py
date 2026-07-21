"""ICP (ideal customer profile): the structured object every search runs from.

Plain-English categories resolve to OSM selectors here; the service the user
sells infers which gaps matter. Agents (or the CLI wizard) elicit the few
fields that can't be inferred, then persist the ICP via the store.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# friendly category -> list of Overpass tag selectors
CATEGORIES: dict[str, list[str]] = {
    "restaurant": ['["amenity"="restaurant"]', '["amenity"="fast_food"]'],
    "cafe": ['["amenity"="cafe"]'],
    "bar": ['["amenity"="bar"]', '["amenity"="pub"]'],
    "bakery": ['["shop"="bakery"]'],
    "dentist": ['["amenity"="dentist"]', '["healthcare"="dentist"]'],
    "doctor": ['["amenity"="doctors"]', '["healthcare"="doctor"]'],
    "vet": ['["amenity"="veterinary"]'],
    "pharmacy": ['["amenity"="pharmacy"]'],
    "optician": ['["shop"="optician"]'],
    "salon": ['["shop"="hairdresser"]', '["shop"="beauty"]'],
    "barber": ['["shop"="hairdresser"]'],
    "tattoo": ['["shop"="tattoo"]'],
    "gym": ['["leisure"="fitness_centre"]'],
    "plumber": ['["craft"="plumber"]'],
    "electrician": ['["craft"="electrician"]'],
    "roofer": ['["craft"="roofer"]'],
    "carpenter": ['["craft"="carpenter"]'],
    "painter": ['["craft"="painter"]'],
    "photographer": ['["craft"="photographer"]'],
    "car_repair": ['["shop"="car_repair"]'],
    "car_dealer": ['["shop"="car"]'],
    "florist": ['["shop"="florist"]'],
    "pet": ['["shop"="pet"]', '["shop"="pet_grooming"]'],
    "lawyer": ['["office"="lawyer"]'],
    "accountant": ['["office"="accountant"]'],
    "real_estate": ['["office"="estate_agent"]'],
    "insurance": ['["office"="insurance"]'],
    "hotel": ['["tourism"="hotel"]', '["tourism"="guest_house"]'],
    "laundry": ['["shop"="laundry"]', '["shop"="dry_cleaning"]'],
    "furniture": ['["shop"="furniture"]'],
    "jewelry": ['["shop"="jewelry"]'],
    "butcher": ['["shop"="butcher"]'],
    "greengrocer": ['["shop"="greengrocer"]'],
    "bookshop": ['["shop"="books"]'],
}

# gaps the engine can compute, with default weights.
# site gaps come from the live check; review gaps from agent-contributed
# review signals (see `leadshoot review add`).
GAP_WEIGHTS: dict[str, float] = {
    "broken_site": 1.0,
    "no_website": 0.9,
    "inactive_social": 0.8,
    "weak_reviews": 0.7,
    "outdated_tech": 0.7,
    "no_ssl": 0.5,
    "weak_social": 0.5,
    "slow_site": 0.5,
    "diy_builder": 0.45,
    "few_reviews": 0.4,
    "not_mobile": 0.4,
    "no_booking": 0.3,
}

REVIEW_GAPS = ("weak_reviews", "few_reviews")
SOCIAL_GAPS = ("inactive_social", "weak_social")
SIGNAL_GAPS = REVIEW_GAPS + SOCIAL_GAPS  # derived from recorded signals

# service the user sells -> gaps that make a business a lead for them
SERVICES: dict[str, dict[str, float]] = {
    "website_design": {"no_website": 0.9, "broken_site": 1.0, "no_ssl": 0.5},
    "redesign": {"broken_site": 1.0, "outdated_tech": 0.9, "not_mobile": 0.8,
                 "no_ssl": 0.7, "diy_builder": 0.6, "slow_site": 0.5},
    "booking_setup": {"no_booking": 1.0, "no_website": 0.6, "broken_site": 0.6},
    "reputation_management": {"weak_reviews": 1.0, "few_reviews": 0.8,
                              "no_website": 0.3},
    "social_media": {"inactive_social": 1.0, "weak_social": 0.8,
                     "no_website": 0.4},
    "general": dict(GAP_WEIGHTS),
}


@dataclass
class ICP:
    name: str
    area: str
    categories: list[str]
    service: str = "website_design"
    gaps: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    exclude_chains: bool = True
    min_score: int = 30
    prefer_established: bool = True  # users avoid just-started businesses
    provider: str = "osm"  # osm (default) | overture (big open data) | gmaps (BYO)
    mode: str = "gaps"  # gaps (fixable-problem leads) | fit (healthy-buyer leads)

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.area = self.area.strip()
        self.categories = [normalize_category(c) for c in self.categories]
        unknown = [c for c in self.categories if c not in CATEGORIES]
        if unknown:
            raise ValueError(
                f"unknown categories: {unknown}. Known: {sorted(CATEGORIES)}"
            )
        if self.service not in SERVICES:
            raise ValueError(
                f"unknown service '{self.service}'. Known: {sorted(SERVICES)}"
            )
        if not self.weights:
            self.weights = dict(SERVICES[self.service])
        if not self.gaps:
            self.gaps = list(self.weights)
        bad = [g for g in self.gaps if g not in GAP_WEIGHTS]
        if bad:
            raise ValueError(f"unknown gaps: {bad}. Known: {sorted(GAP_WEIGHTS)}")
        # custom gap lists (user confirmed outside-niche targeting) still
        # need a weight for every gap they name
        for g in self.gaps:
            self.weights.setdefault(g, GAP_WEIGHTS[g])
        if self.provider not in ("osm", "overture", "gmaps"):
            raise ValueError("provider must be 'osm', 'overture', or 'gmaps'")
        if self.mode not in ("gaps", "fit"):
            raise ValueError("mode must be 'gaps' or 'fit'")
        if self.mode == "fit":
            # fit niches sell TO healthy businesses: nothing is flagged,
            # health ranks. Gap weights are ignored by the fit scorer.
            self.gaps = []

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "area": self.area,
            "categories": self.categories,
            "service": self.service,
            "gaps": self.gaps,
            "weights": self.weights,
            "exclude_chains": self.exclude_chains,
            "min_score": self.min_score,
            "prefer_established": self.prefer_established,
            "provider": self.provider,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ICP":
        return cls(
            name=d["name"],
            area=d["area"],
            categories=list(d["categories"]),
            service=d.get("service", "website_design"),
            gaps=list(d.get("gaps", [])),
            weights=dict(d.get("weights", {})),
            exclude_chains=bool(d.get("exclude_chains", True)),
            min_score=int(d.get("min_score", 30)),
            prefer_established=bool(d.get("prefer_established", True)),
            provider=d.get("provider", "osm"),
            mode=d.get("mode", "gaps"),
        )


_ALIASES = {
    "restaurants": "restaurant", "cafes": "cafe", "coffee": "cafe",
    "coffee_shop": "cafe", "dentists": "dentist", "doctors": "doctor",
    "hairdresser": "salon", "hair": "salon", "beauty": "salon",
    "salons": "salon", "bars": "bar", "pub": "bar", "gyms": "gym",
    "fitness": "gym", "plumbers": "plumber", "electricians": "electrician",
    "roofers": "roofer", "vets": "vet", "veterinary": "vet",
    "lawyers": "lawyer", "attorney": "lawyer", "accountants": "accountant",
    "hotels": "hotel", "auto_repair": "car_repair", "mechanic": "car_repair",
    "realtor": "real_estate", "estate_agent": "real_estate",
    "bakeries": "bakery", "florists": "florist", "pets": "pet",
    "pharmacies": "pharmacy", "books": "bookshop",
}


def normalize_category(cat: str) -> str:
    c = cat.strip().lower().replace(" ", "_").replace("-", "_")
    return _ALIASES.get(c, c)


def selectors_for(categories: list[str]) -> list[tuple[str, str]]:
    """[(friendly_category, overpass_selector), ...]"""
    out: list[tuple[str, str]] = []
    for cat in categories:
        for sel in CATEGORIES[normalize_category(cat)]:
            out.append((normalize_category(cat), sel))
    return out


def infer_gaps(service: str) -> dict[str, float]:
    return dict(SERVICES.get(service, SERVICES["general"]))
