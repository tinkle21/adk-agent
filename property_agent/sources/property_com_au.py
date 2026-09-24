"""Value and rent estimates from property.com.au (PropTrack AVM).

A property.com.au profile page shows an estimated value with a confidence
level (High / Medium / Low) and usually a rental estimate. Like the listing
source, we look for estimate-shaped objects in the embedded JSON and fall back
to the visible text if that fails.
"""

from __future__ import annotations

import re
import urllib.parse

from ..models import Listing, Valuation
from .http import Fetcher, embedded_json

_PROFILE_URL = re.compile(r"https?://(?:www\.)?property\.com\.au/[^\s\"'<>]*?-pid-\d+/?")

_VALUE_KEYS = ("value", "estimate", "estimatedValue", "midPrice", "mid", "midValue", "price")
_LOW_KEYS = ("lowerPrice", "low", "lowValue", "lowerRange", "min", "lower")
_HIGH_KEYS = ("upperPrice", "high", "highValue", "upperRange", "max", "upper")
_CONFIDENCE_KEYS = ("confidence", "confidenceLevel", "confidenceRating")


def _number(value) -> float | None:
    if isinstance(value, dict):
        value = value.get("value", value.get("amount"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d.]", "", value)
        try:
            return float(digits) if digits else None
        except ValueError:
            return None
    return None


def _first(node: dict, keys) -> float | None:
    for key in keys:
        if key in node:
            number = _number(node[key])
            if number:
                return number
    return None


def _normalise_confidence(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.lower()
    for level in ("high", "medium", "low"):
        if level in value:
            return level
    return None


def _estimates(obj, path=()):
    """Yield (path, node) for every object that looks like an AVM estimate."""
    if isinstance(obj, dict):
        confidence = next((obj[k] for k in _CONFIDENCE_KEYS if k in obj), None)
        if confidence is not None and (_first(obj, _VALUE_KEYS) or _first(obj, _LOW_KEYS)):
            yield path, obj
        for key, value in obj.items():
            yield from _estimates(value, path + (str(key),))
    elif isinstance(obj, list):
        for value in obj:
            yield from _estimates(value, path)


def _is_rent(path) -> bool:
    return any("rent" in part.lower() for part in path)


def parse_profile_page(html: str, url: str | None = None) -> Valuation | None:
    sale = rent = None
    for blob in embedded_json(html):
        for path, node in _estimates(blob):
            if _is_rent(path):
                rent = rent or node
            else:
                sale = sale or node
    if sale:
        low, high = _first(sale, _LOW_KEYS), _first(sale, _HIGH_KEYS)
        value = _first(sale, _VALUE_KEYS)
        if value is None and low and high:
            value = (low + high) / 2
        confidence = _normalise_confidence(next(sale[k] for k in _CONFIDENCE_KEYS if k in sale))
        weekly_rent = _first(rent, _VALUE_KEYS) if rent else None
        return Valuation(value, confidence, low, high, weekly_rent, url)
    return _parse_visible_text(html, url)


def _parse_visible_text(html: str, url: str | None) -> Valuation | None:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    confidence = re.search(r"\b(high|medium|low)\s+confidence\b", text, re.I)
    value = re.search(r"estimated value[^$]{0,80}\$\s*([\d,.]+\s*[km]?)", text, re.I)
    if not (confidence and value):
        return None
    rent = re.search(r"rental estimate[^$]{0,80}\$\s*([\d,]+)\s*(?:/|per)\s*w", text, re.I)
    amount = value.group(1).replace(",", "").strip().lower()
    multiplier = 1_000_000 if amount.endswith("m") else 1_000 if amount.endswith("k") else 1
    return Valuation(
        estimated_value=float(amount.rstrip("km")) * multiplier,
        confidence=confidence.group(1).lower(),
        weekly_rent_estimate=float(rent.group(1).replace(",", "")) if rent else None,
        source_url=url,
    )


class PropertyComAuSource:
    def __init__(self, fetcher: Fetcher):
        self.fetcher = fetcher

    def find_profile_url(self, listing: Listing) -> str | None:
        """The property.com.au page for a listing's address.

        Uses the link embedded in the listing when there is one; otherwise
        searches the web for the address restricted to property.com.au.
        """
        if listing.property_profile_url:
            return listing.property_profile_url
        query = f'site:property.com.au "{listing.address}"'
        html = self.fetcher.get("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query))
        html = urllib.parse.unquote(html)
        street_number = re.match(r"\s*([\w/-]+)", listing.address)
        for candidate in _PROFILE_URL.findall(html):
            # Guard against a neighbouring property: the slug must contain the street number.
            number = street_number.group(1).lower().replace("/", "-") if street_number else None
            if not number or f"/{number}-" in candidate.lower():
                return candidate
        return None

    def valuation(self, listing: Listing) -> Valuation | None:
        url = self.find_profile_url(listing)
        if not url:
            return None
        return self.valuation_for_url(url)

    def valuation_for_url(self, url: str) -> Valuation | None:
        return parse_profile_page(self.fetcher.get(url), url)
