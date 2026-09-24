"""The three investment rules.

1. Asking price is close to the property.com.au estimated value.
2. That estimate has an accepted confidence level (high by default).
3. Estimated rent covers the repayment on a loan of the price less the deposit
   (80% loan at 6.1% over 30 years by default).
"""

from __future__ import annotations

from .config import Criteria
from .finance import gross_yield, loan_amount, monthly_repayment, weekly_to_monthly
from .models import Evaluation, Listing, Valuation
from .pricing import parse_price


def evaluate(listing: Listing, valuation: Valuation | None, criteria: Criteria) -> Evaluation:
    asking = parse_price(listing.price_text, criteria.range_price_basis)
    ev = Evaluation(listing=listing, valuation=valuation, asking_price=asking)

    if asking is None:
        ev.reasons.append(f"No usable asking price ('{listing.price_text}')")
        return ev
    if valuation is None or not valuation.estimated_value:
        ev.reasons.append("No property.com.au estimate found")
        return ev

    failures = 0
    near = True
    margin = criteria.near_miss_margin

    # Rule 1: price close to estimate.
    ev.price_gap = (asking - valuation.estimated_value) / valuation.estimated_value
    if abs(ev.price_gap) > criteria.price_tolerance:
        failures += 1
        near &= abs(ev.price_gap) <= criteria.price_tolerance + margin
        ev.reasons.append(
            f"Asking ${asking:,.0f} is {ev.price_gap:+.1%} vs estimate "
            f"${valuation.estimated_value:,.0f} (limit ±{criteria.price_tolerance:.0%})"
        )

    # Rule 2: estimate confidence.
    accepted = [c.lower() for c in criteria.accepted_confidence]
    if (valuation.confidence or "").lower() not in accepted:
        failures += 1
        near = False
        ev.reasons.append(f"Estimate confidence is {valuation.confidence or 'unknown'}, need {'/'.join(accepted)}")

    # Rule 3: rent covers the loan repayment.
    ev.loan_amount = loan_amount(asking, criteria.deposit_pct)
    ev.monthly_repayment = monthly_repayment(ev.loan_amount, criteria.interest_rate, criteria.loan_term_years)
    if valuation.weekly_rent_estimate:
        ev.monthly_rent = weekly_to_monthly(valuation.weekly_rent_estimate)
        ev.rent_coverage = ev.monthly_rent / ev.monthly_repayment
        ev.gross_yield = gross_yield(asking, valuation.weekly_rent_estimate)
        if ev.rent_coverage < criteria.min_rent_coverage:
            failures += 1
            near &= ev.rent_coverage >= criteria.min_rent_coverage - margin
            ev.reasons.append(
                f"Rent ${ev.monthly_rent:,.0f}/mo covers {ev.rent_coverage:.0%} of the "
                f"${ev.monthly_repayment:,.0f}/mo repayment"
            )
    else:
        failures += 1
        near = False
        ev.reasons.append("No rental estimate found")

    ev.passed = failures == 0
    ev.near_miss = not ev.passed and failures == 1 and near
    return ev


def rank(evaluations: list[Evaluation]) -> list[Evaluation]:
    """Best first: strongest rent coverage, then biggest discount to estimate."""
    return sorted(evaluations, key=lambda e: (-(e.rent_coverage or 0), e.price_gap or 0))
