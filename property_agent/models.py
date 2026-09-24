"""Plain data records passed between sources, the screener and reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Listing:
    """A for-sale listing from realestate.com.au."""

    listing_id: str
    address: str
    url: str
    price_text: str
    suburb: str = ""
    state: str = ""
    postcode: str = ""
    property_type: str = ""
    bedrooms: int | None = None
    bathrooms: int | None = None
    parking: int | None = None
    property_profile_url: str | None = None  # property.com.au page, if linked


@dataclass
class Valuation:
    """A property.com.au (PropTrack) estimate for one property."""

    estimated_value: float | None
    confidence: str | None  # "high" | "medium" | "low"
    value_low: float | None = None
    value_high: float | None = None
    weekly_rent_estimate: float | None = None
    source_url: str | None = None


@dataclass
class Evaluation:
    listing: Listing
    valuation: Valuation | None
    asking_price: float | None
    loan_amount: float | None = None
    monthly_repayment: float | None = None
    monthly_rent: float | None = None
    rent_coverage: float | None = None
    gross_yield: float | None = None
    price_gap: float | None = None  # (asking - estimate) / estimate
    passed: bool = False
    near_miss: bool = False
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
