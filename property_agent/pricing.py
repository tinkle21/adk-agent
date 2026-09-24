"""Turns Australian listing price text into a number.

Listings show prices as free text: "$649,000", "Offers over $620k",
"$600,000 - $650,000", "Contact Agent", "Auction". Unpriced listings return None.
"""

from __future__ import annotations

import re

_AMOUNT = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(k|m|mil|million)?\b", re.I)


def _amounts(text: str) -> list[float]:
    values = []
    for number, suffix in _AMOUNT.findall(text):
        value = float(number.replace(",", ""))
        suffix = suffix.lower()
        if suffix == "k":
            value *= 1_000
        elif suffix in ("m", "mil", "million"):
            value *= 1_000_000
        # Ignore stray small numbers ("3 bed", "2 days") - no home costs under $50k.
        if value >= 50_000:
            values.append(value)
    return values


def parse_price(text: str | None, range_basis: str = "high") -> float | None:
    if not text:
        return None
    values = _amounts(text)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    low, high = min(values), max(values)
    return {"low": low, "mid": (low + high) / 2}.get(range_basis, high)
