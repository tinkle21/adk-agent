"""Loan maths used by the investment criteria."""

from __future__ import annotations


def loan_amount(price: float, deposit_pct: float = 0.20) -> float:
    return price * (1 - deposit_pct)


def monthly_repayment(principal: float, annual_rate: float = 0.061, years: int = 30) -> float:
    """Principal-and-interest monthly repayment (EMI)."""
    n = years * 12
    r = annual_rate / 12
    if r == 0:
        return principal / n
    return principal * r / (1 - (1 + r) ** -n)


def weekly_to_monthly(weekly: float) -> float:
    return weekly * 52 / 12


def breakeven_weekly_rent(
    price: float, deposit_pct: float = 0.20, annual_rate: float = 0.061, years: int = 30
) -> float:
    """Weekly rent needed for the rent to exactly cover the repayment."""
    emi = monthly_repayment(loan_amount(price, deposit_pct), annual_rate, years)
    return emi * 12 / 52


def gross_yield(price: float, weekly_rent: float) -> float:
    return weekly_rent * 52 / price
