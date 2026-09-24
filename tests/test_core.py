from pathlib import Path

import pytest

from property_agent.config import Criteria, SearchSettings
from property_agent.finance import breakeven_weekly_rent, loan_amount, monthly_repayment
from property_agent.models import Listing, Valuation
from property_agent.pricing import parse_price
from property_agent.scan import run_scan
from property_agent.screener import evaluate
from property_agent.sources.property_com_au import parse_profile_page
from property_agent.sources.realestate import parse_search_page, search_url

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = Path(__file__).parent.parent / "examples" / "sample_listings.json"


def test_repayment_matches_standard_formula():
    # $400k at 6.1% over 30 years is about $2,424/month.
    assert monthly_repayment(400_000, 0.061, 30) == pytest.approx(2423.93, abs=0.5)
    assert loan_amount(500_000, 0.20) == 400_000
    assert breakeven_weekly_rent(500_000) == pytest.approx(2423.93 * 12 / 52, abs=0.2)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("$649,000", 649_000),
        ("Offers over $620k", 620_000),
        ("$600,000 - $650,000", 650_000),
        ("$1.2m", 1_200_000),
        ("Contact Agent", None),
        ("Auction 3 bed", None),
        (None, None),
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


def test_parse_price_range_basis():
    assert parse_price("$600k-$650k", "low") == 600_000
    assert parse_price("$600k-$650k", "mid") == 625_000


def _listing(price="$480,000"):
    return Listing("1", "12 Example St", "https://x", price)


def test_evaluate_pass():
    ev = evaluate(_listing(), Valuation(490_000, "high", weekly_rent_estimate=580), Criteria())
    assert ev.passed, ev.reasons
    assert ev.rent_coverage > 1


def test_evaluate_fails_each_rule():
    c = Criteria()
    assert not evaluate(_listing("$600,000"), Valuation(490_000, "high", weekly_rent_estimate=900), c).passed
    assert not evaluate(_listing(), Valuation(490_000, "medium", weekly_rent_estimate=580), c).passed
    low_rent = evaluate(_listing(), Valuation(490_000, "high", weekly_rent_estimate=520), c)
    assert not low_rent.passed and low_rent.near_miss
    assert not evaluate(_listing("Contact agent"), Valuation(490_000, "high", weekly_rent_estimate=580), c).passed
    assert not evaluate(_listing(), None, c).passed


def test_search_url():
    s = SearchSettings(property_types=["house", "townhouse"], min_price=300000, max_price=750000, min_bedrooms=2)
    assert search_url("ipswich, qld 4305", s, 2) == (
        "https://www.realestate.com.au/buy/property-house-townhouse-with-2-bedrooms-between-300000-750000"
        "-in-ipswich,+qld+4305/list-2?activeSort=list-date&includeSurrounding=false"
    )


def test_parse_search_page():
    listings = parse_search_page((FIXTURES / "rea_search.html").read_text())
    by_id = {l.listing_id: l for l in listings}
    first = by_id["145000001"]
    assert first.price_text == "Offers over $480,000"
    assert first.address == "12 Example St, Ipswich, Qld 4305"
    assert first.bedrooms == 3 and first.parking == 2 and first.state == "QLD"
    assert first.url.endswith("145000001")
    assert by_id["145000002"].address == "3/5 Sample Rd, Ipswich QLD 4305"


def test_parse_profile_page_json():
    v = parse_profile_page((FIXTURES / "property_profile.html").read_text())
    assert (v.estimated_value, v.confidence, v.weekly_rent_estimate) == (490_000, "high", 580)
    assert (v.value_low, v.value_high) == (450_000, 530_000)


def test_parse_profile_page_text_fallback():
    v = parse_profile_page((FIXTURES / "property_profile_text.html").read_text())
    assert (v.estimated_value, v.confidence, v.weekly_rent_estimate) == (612_000, "high", 560)


def test_offline_scan():
    result = run_scan(offline=SAMPLE, write=False)
    assert [e.listing.listing_id for e in result.matches] == ["1002", "1001"]
    assert {e.listing.listing_id for e in result.near_misses} == set()
    assert "## Matches" in result.markdown
