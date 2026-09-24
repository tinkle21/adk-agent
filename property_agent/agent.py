"""Google ADK research agent for Australian investment properties.

Run it interactively with `adk web` or `adk run property_agent` from the repo
root. The scheduled job calls `property_agent.scan` directly and doesn't need
an LLM.
"""

from __future__ import annotations

import os

from google.adk.agents import Agent

from .config import ROOT, load_settings
from .finance import breakeven_weekly_rent, gross_yield, loan_amount, monthly_repayment, weekly_to_monthly
from .models import Listing, Valuation
from .screener import evaluate

MODEL = os.environ.get("ADK_MODEL", "gemini-2.5-flash")


def _summary(e) -> dict:
    return {
        "address": e.listing.address,
        "url": e.listing.url,
        "asking": e.listing.price_text,
        "estimate": e.valuation.estimated_value if e.valuation else None,
        "confidence": e.valuation.confidence if e.valuation else None,
        "weekly_rent_estimate": e.valuation.weekly_rent_estimate if e.valuation else None,
        "price_vs_estimate": round(e.price_gap, 4) if e.price_gap is not None else None,
        "monthly_repayment": round(e.monthly_repayment) if e.monthly_repayment else None,
        "rent_coverage": round(e.rent_coverage, 3) if e.rent_coverage else None,
        "gross_yield": round(e.gross_yield, 4) if e.gross_yield else None,
        "passed": e.passed,
        "reasons": e.reasons,
    }


def run_market_scan(locations: list[str] | None = None) -> dict:
    """Scans realestate.com.au listings and checks each one against the investment rules.

    Args:
        locations: Optional list of realestate.com.au locations such as
            "ipswich, qld 4305". Uses the locations in config.toml when omitted.

    Returns:
        Matches, near misses, counts, any fetch errors and the report path.
    """
    from .scan import run_scan

    settings = load_settings()
    if locations:
        settings.search.locations = locations
    result = run_scan(settings)
    return {
        "listings_checked": len(result.evaluations),
        "matches": [_summary(e) for e in result.matches],
        "near_misses": [_summary(e) for e in result.near_misses],
        "errors": result.errors,
        "report_path": str(result.report_path) if result.report_path else None,
    }


def check_listing(listing_url: str) -> dict:
    """Checks one realestate.com.au listing against the investment rules.

    Args:
        listing_url: Full realestate.com.au listing URL.

    Returns:
        The listing, its property.com.au estimate and whether it passes each rule.
    """
    from .sources.http import Fetcher
    from .sources.property_com_au import PropertyComAuSource
    from .sources.realestate import RealestateSource

    settings = load_settings()
    fetcher = Fetcher(settings.fetch)
    try:
        listing = RealestateSource(fetcher, settings.search).listing(listing_url)
        if not listing:
            return {"error": "Could not read the listing page."}
        valuation = PropertyComAuSource(fetcher).valuation(listing)
    except Exception as exc:
        return {"error": str(exc)}
    finally:
        fetcher.close()
    return _summary(evaluate(listing, valuation, settings.criteria))


def check_numbers(
    asking_price: float,
    estimated_value: float,
    confidence: str,
    weekly_rent: float,
) -> dict:
    """Checks a property against the investment rules using figures you supply.

    Use this when the user gives numbers directly or when scraping is blocked.

    Args:
        asking_price: Asking price in AUD.
        estimated_value: property.com.au estimated value in AUD.
        confidence: property.com.au estimate confidence: "high", "medium" or "low".
        weekly_rent: Estimated rent in AUD per week.

    Returns:
        Loan, repayment, rent coverage, yield and whether each rule passes.
    """
    listing = Listing(listing_id="manual", address="(manual input)", url="", price_text=f"${asking_price:,.0f}")
    valuation = Valuation(estimated_value=estimated_value, confidence=confidence, weekly_rent_estimate=weekly_rent)
    return _summary(evaluate(listing, valuation, load_settings().criteria))


def loan_calculator(
    price: float,
    deposit_pct: float = 0.20,
    interest_rate: float = 0.061,
    loan_term_years: int = 30,
    weekly_rent: float = 0.0,
) -> dict:
    """Works out the loan, monthly repayment and break-even rent for a purchase price.

    Args:
        price: Purchase price in AUD.
        deposit_pct: Deposit as a fraction, e.g. 0.2 for 20%.
        interest_rate: Annual interest rate as a fraction, e.g. 0.061 for 6.1%.
        loan_term_years: Loan term in years.
        weekly_rent: Optional weekly rent to compare against the repayment.

    Returns:
        Loan amount, monthly repayment, break-even weekly rent and, if rent is
        given, rent coverage and gross yield.
    """
    loan = loan_amount(price, deposit_pct)
    emi = monthly_repayment(loan, interest_rate, loan_term_years)
    out = {
        "loan_amount": round(loan),
        "monthly_repayment": round(emi, 2),
        "breakeven_weekly_rent": round(breakeven_weekly_rent(price, deposit_pct, interest_rate, loan_term_years), 2),
    }
    if weekly_rent:
        out["rent_coverage"] = round(weekly_to_monthly(weekly_rent) / emi, 3)
        out["gross_yield"] = round(gross_yield(price, weekly_rent), 4)
    return out


def latest_report() -> dict:
    """Returns the most recent saved scan report (markdown)."""
    path = ROOT / "reports" / "latest.md"
    if not path.exists():
        return {"error": "No scan has been run yet."}
    return {"report": path.read_text()}


_criteria = load_settings().criteria

root_agent = Agent(
    name="au_property_researcher",
    model=MODEL,
    description="Finds Australian investment properties whose rent covers the mortgage.",
    instruction=f"""You are a property investment research assistant for the Australian market.

A property is a good investment when ALL of these hold:
1. It is listed for sale on realestate.com.au.
2. Its asking price is within ±{_criteria.price_tolerance:.0%} of the property.com.au estimated
   value, and that estimate has {'/'.join(_criteria.accepted_confidence)} confidence.
3. The estimated rent covers the monthly repayment on a loan of the price less a
   {_criteria.deposit_pct:.0%} deposit, at {_criteria.interest_rate:.2%} p.a. over {_criteria.loan_term_years} years.

Tools:
- run_market_scan: full scan of the configured (or given) locations. Takes minutes.
- check_listing: evaluate one realestate.com.au URL.
- check_numbers: evaluate figures the user provides.
- loan_calculator: repayment / break-even rent maths.
- latest_report: the last scheduled scan's report.

Always use the tools for numbers; never estimate prices, rents or repayments
yourself. Present matches best first with address, link, asking price, estimate
and confidence, weekly rent, monthly repayment and how much of it rent covers.
If a tool reports that a site blocked the request, say so plainly and explain
that FETCH_URL_TEMPLATE needs a scraping provider; don't invent results.
Remind the user that estimates exclude strata, rates, insurance, management
fees and vacancy, and that this is research, not financial advice.""",
    tools=[run_market_scan, check_listing, check_numbers, loan_calculator, latest_report],
)
